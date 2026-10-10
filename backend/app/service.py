"""Business-state coordinator for graph interrupts and reviewer decisions."""

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
from langgraph.types import Command
from psycopg.types.json import Jsonb

from app.models import ApprovalDecision, OperationRequest
from app.observability import current_request_id, log_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    tenant_id: UUID
    role: str


class OperationService:
    def __init__(self, database_url: str, graph) -> None:
        self.database_url = database_url
        self.graph = graph

    async def get(self, actor: Actor, operation_id: UUID) -> dict:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cursor = await conn.execute(
                """SELECT o.id, o.status, o.requester_id, o.failure_code,
                          d.payload, d.payload_hash
                   FROM operations o LEFT JOIN action_drafts d
                     ON d.operation_id = o.id AND d.version = 1
                   WHERE o.id = %s AND o.tenant_id = %s""",
                (operation_id, actor.tenant_id),
            )
            row = await cursor.fetchone()
        if row is None or (actor.role == "requester" and row[2] != actor.user_id):
            raise LookupError("Operation not found")
        return {
            "id": str(row[0]),
            "status": row[1],
            "failure_code": row[3],
            "draft": row[4],
            "draft_hash": row[5],
        }

    async def create(self, actor: Actor, request: OperationRequest) -> UUID:
        if actor.role not in {"requester", "reviewer", "admin"}:
            raise PermissionError("Requester role required")
        operation_id = uuid4()
        trace_id = UUID(current_request_id()) if current_request_id() else uuid4()
        thread_id = str(operation_id)
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO operations
                       (id, tenant_id, requester_id, request_text, customer_id,
                        status, graph_thread_id, trace_id)
                       VALUES (%s, %s, %s, %s, %s, 'RECEIVED', %s, %s)""",
                    (
                        operation_id,
                        actor.tenant_id,
                        actor.user_id,
                        request.request_text,
                        request.customer_id,
                        thread_id,
                        trace_id,
                    ),
                )
                await self._audit(
                    conn,
                    actor.tenant_id,
                    operation_id,
                    actor.user_id,
                    "operation.created",
                    trace_id,
                )
        config = {"configurable": {"thread_id": thread_id}}
        try:
            state = await self.graph.ainvoke(
                {
                    "tenant_id": str(actor.tenant_id),
                    "request_text": request.request_text,
                    "customer_id": request.customer_id,
                },
                config,
            )
            if "__interrupt__" not in state:
                raise RuntimeError("Graph did not interrupt for approval")
            snapshot = await self.graph.aget_state(config)
            draft = snapshot.values["draft"]
            draft_hash = snapshot.values["draft_hash"]
            async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """INSERT INTO action_drafts
                           (operation_id, version, payload, payload_hash)
                           VALUES (%s, 1, %s, %s)""",
                        (operation_id, Jsonb(draft), draft_hash),
                    )
                    await conn.execute(
                        """UPDATE operations SET status = 'AWAITING_APPROVAL',
                           updated_at = now() WHERE id = %s""",
                        (operation_id,),
                    )
                    await self._audit(
                        conn,
                        actor.tenant_id,
                        operation_id,
                        None,
                        "draft.ready",
                        trace_id,
                    )
        except Exception:
            log_event(
                logger,
                "operation.draft_failed",
                tenant_id=str(actor.tenant_id),
                workflow_thread_id=thread_id,
            )
            async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """UPDATE operations SET status = 'FAILED',
                           failure_code = 'DRAFT_FAILED', updated_at = now()
                           WHERE id = %s""",
                        (operation_id,),
                    )
                    await self._audit(
                        conn,
                        actor.tenant_id,
                        operation_id,
                        None,
                        "operation.failed",
                        trace_id,
                    )
            raise
        log_event(
            logger,
            "operation.awaiting_approval",
            tenant_id=str(actor.tenant_id),
            workflow_thread_id=thread_id,
        )
        return operation_id

    async def decide(
        self, actor: Actor, operation_id: UUID, decision: ApprovalDecision
    ) -> None:
        if actor.role not in {"reviewer", "admin"}:
            raise PermissionError("Reviewer role required")
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.transaction():
                cursor = await conn.execute(
                    """SELECT status, trace_id, requester_id FROM operations
                       WHERE id = %s AND tenant_id = %s FOR UPDATE""",
                    (operation_id, actor.tenant_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise LookupError("Operation not found")
                status, trace_id, requester_id = row
                if requester_id == actor.user_id:
                    raise PermissionError("Requester cannot review own operation")
                cursor = await conn.execute(
                    """SELECT payload, payload_hash FROM action_drafts
                       WHERE operation_id = %s AND version = 1""",
                    (operation_id,),
                )
                draft_row = await cursor.fetchone()
                if draft_row is None or draft_row[1] != decision.draft_hash:
                    raise ValueError("Approval targets a stale draft")
                if status not in {"AWAITING_APPROVAL", "APPROVED", "REJECTED"}:
                    raise ValueError(f"Operation cannot be reviewed in state {status}")
                cursor = await conn.execute(
                    """SELECT decision FROM approvals
                       WHERE operation_id = %s AND draft_version = 1""",
                    (operation_id,),
                )
                existing = await cursor.fetchone()
                if existing:
                    if existing[0] != decision.decision:
                        raise ValueError("Decision already recorded")
                else:
                    await conn.execute(
                        """INSERT INTO approvals
                           (operation_id, draft_version, draft_hash, reviewer_id,
                            decision, reason) VALUES (%s, 1, %s, %s, %s, %s)""",
                        (
                            operation_id,
                            decision.draft_hash,
                            actor.user_id,
                            decision.decision,
                            decision.reason,
                        ),
                    )
                    next_status = (
                        "APPROVED" if decision.decision == "approved" else "REJECTED"
                    )
                    await conn.execute(
                        """UPDATE operations SET status = %s, updated_at = now()
                           WHERE id = %s""",
                        (next_status, operation_id),
                    )
                    if decision.decision == "approved":
                        draft = draft_row[0]
                        key = f"{operation_id}:1:{decision.draft_hash}"
                        await conn.execute(
                            """INSERT INTO outbox_actions
                               (id, operation_id, draft_version, draft_hash, provider,
                                payload, idempotency_key, status)
                               VALUES (%s, %s, 1, %s, %s, %s, %s, 'held')""",
                            (
                                uuid4(),
                                operation_id,
                                decision.draft_hash,
                                draft["provider"],
                                Jsonb(draft),
                                key,
                            ),
                        )
                    await self._audit(
                        conn,
                        actor.tenant_id,
                        operation_id,
                        actor.user_id,
                        f"approval.{decision.decision}",
                        trace_id,
                    )
        await self.recover_resume(operation_id, decision)
        log_event(
            logger,
            f"operation.{decision.decision}",
            tenant_id=str(actor.tenant_id),
            workflow_thread_id=str(operation_id),
        )

    async def recover_resume(
        self, operation_id: UUID, decision: ApprovalDecision
    ) -> None:
        """Repeatable after a crash between approval commit and graph resume."""
        config = {"configurable": {"thread_id": str(operation_id)}}
        snapshot = await self.graph.aget_state(config)
        if snapshot.values.get("decision") != decision.decision:
            if not snapshot.next or "await_approval" not in snapshot.next:
                raise RuntimeError("Graph is not waiting for the recorded approval")
            await self.graph.ainvoke(Command(resume=decision.model_dump()), config)
        if decision.decision == "approved":
            async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """UPDATE outbox_actions SET status = 'pending'
                           WHERE operation_id = %s AND draft_hash = %s
                             AND status = 'held'""",
                        (operation_id, decision.draft_hash),
                    )

    @staticmethod
    async def _audit(conn, tenant_id, operation_id, actor_id, event_type, trace_id):
        await conn.execute(
            """INSERT INTO audit_events
               (id, tenant_id, operation_id, actor_id, event_type, trace_id, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                uuid4(),
                tenant_id,
                operation_id,
                actor_id,
                event_type,
                trace_id,
                Jsonb({}),
            ),
        )
