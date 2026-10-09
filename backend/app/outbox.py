"""Transactional outbox worker; no provider call occurs inside LangGraph."""

import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.models import ActionDraft
from app.providers import (
    PermanentDeliveryError,
    Receipt,
    RetryableDeliveryError,
    UnknownDeliveryOutcome,
)
from app.service import Actor

logger = logging.getLogger(__name__)


class DeliveryProvider(Protocol):
    async def send(self, draft: ActionDraft, key: str) -> Receipt: ...


@dataclass(frozen=True)
class ClaimedAction:
    id: UUID
    operation_id: UUID
    tenant_id: UUID
    trace_id: UUID
    payload: dict
    key: str
    attempt: int
    provider: str


def backoff_seconds(attempt: int, key: str) -> int:
    base = min(3600, 2 ** min(attempt, 11))
    jitter = int(hashlib.sha256(f"{key}:{attempt}".encode()).hexdigest()[:2], 16) % 6
    return base + jitter


class OutboxDispatcher:
    def __init__(
        self,
        database_url: str,
        providers: dict[str, DeliveryProvider],
        max_attempts: int = 5,
    ) -> None:
        self.database_url = database_url
        self.providers = providers
        self.max_attempts = max_attempts

    async def run_once(self) -> bool:
        action = await self._claim()
        if action is None:
            return False
        try:
            receipt = await self.providers[action.provider].send(
                ActionDraft.model_validate(action.payload), action.key
            )
        except RetryableDeliveryError as error:
            await self._settle(action, "retry", str(error))
        except PermanentDeliveryError as error:
            await self._settle(action, "failed", str(error))
        except UnknownDeliveryOutcome as error:
            await self._settle(action, "unknown", str(error))
        except Exception:
            logger.exception(
                "unexpected dispatch result", extra={"action_id": str(action.id)}
            )
            # The request may have reached the provider. Quarantine the action.
            await self._settle(action, "unknown", "unexpected_provider_error")
        else:
            await self._settle(action, "sent", receipt.provider_id)
        return True

    async def _claim(self) -> ClaimedAction | None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.transaction():
                cursor = await conn.execute(
                    """SELECT a.id, a.operation_id, o.tenant_id, o.trace_id,
                              a.payload, a.idempotency_key, a.attempt_count, a.provider
                       FROM outbox_actions a JOIN operations o ON o.id = a.operation_id
                       WHERE a.status IN ('pending', 'retry_pending')
                         AND o.status IN ('APPROVED', 'RETRY_PENDING')
                         AND (a.next_attempt_at IS NULL OR a.next_attempt_at <= now())
                       ORDER BY a.created_at
                       FOR UPDATE OF a SKIP LOCKED LIMIT 1"""
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                action = ClaimedAction(*row[:6], row[6] + 1, row[7])
                await conn.execute(
                    """UPDATE outbox_actions SET status = 'sending',
                       attempt_count = %s, claimed_at = now() WHERE id = %s""",
                    (action.attempt, action.id),
                )
                await conn.execute(
                    "UPDATE operations SET status = 'DISPATCHING' WHERE id = %s",
                    (action.operation_id,),
                )
                return action

    async def _settle(self, action: ClaimedAction, outcome: str, detail: str) -> None:
        if outcome == "retry" and action.attempt >= self.max_attempts:
            outcome = "failed"
            detail = "retry_exhausted"
        outbox_status = {
            "sent": "sent",
            "retry": "retry_pending",
            "failed": "failed",
            "unknown": "unknown",
        }[outcome]
        operation_status = {
            "sent": "COMPLETED",
            "retry": "RETRY_PENDING",
            "failed": "FAILED",
            "unknown": "DELIVERY_UNKNOWN",
        }[outcome]
        delay = (
            backoff_seconds(action.attempt, action.key) if outcome == "retry" else None
        )
        receipt_id = detail if outcome == "sent" else None
        error_code = detail if outcome != "sent" else None
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.transaction():
                cursor = await conn.execute(
                    """SELECT status, attempt_count FROM outbox_actions
                       WHERE id = %s FOR UPDATE""",
                    (action.id,),
                )
                current = await cursor.fetchone()
                if current is None or current[1] != action.attempt:
                    return
                if current[0] != "sending" and not (
                    current[0] == "unknown" and outcome == "sent"
                ):
                    return
                await conn.execute(
                    """INSERT INTO dispatch_attempts
                       (outbox_id, attempt_number, provider_request_id, result, next_retry_at)
                       VALUES (%s, %s, %s, %s,
                               CASE WHEN %s::integer IS NULL THEN NULL
                                    ELSE now() + %s * interval '1 second' END)
                       ON CONFLICT (outbox_id, attempt_number) DO UPDATE
                       SET provider_request_id = EXCLUDED.provider_request_id,
                           result = EXCLUDED.result,
                           next_retry_at = EXCLUDED.next_retry_at""",
                    (action.id, action.attempt, receipt_id, outcome, delay, delay),
                )
                await conn.execute(
                    """UPDATE outbox_actions SET status = %s, provider_receipt_id = %s,
                       last_error_code = %s,
                       next_attempt_at = CASE WHEN %s::integer IS NULL THEN NULL
                           ELSE now() + %s * interval '1 second' END,
                       unknown_since = CASE WHEN %s = 'unknown' THEN now() ELSE NULL END,
                       claimed_at = NULL WHERE id = %s""",
                    (
                        outbox_status,
                        receipt_id,
                        error_code,
                        delay,
                        delay,
                        outcome,
                        action.id,
                    ),
                )
                await conn.execute(
                    """UPDATE operations SET status = %s, failure_code = %s,
                       updated_at = now() WHERE id = %s""",
                    (operation_status, error_code, action.operation_id),
                )
                await conn.execute(
                    """INSERT INTO audit_events
                       (id, tenant_id, operation_id, event_type, trace_id, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        uuid4(),
                        action.tenant_id,
                        action.operation_id,
                        f"dispatch.{outcome}",
                        action.trace_id,
                        Jsonb({"attempt": action.attempt, "provider": action.provider}),
                    ),
                )

    async def mark_stale_unknown(self, older_than_seconds: int = 120) -> int:
        """Quarantine claimed sends after worker crashes; never resend blindly."""
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.transaction():
                cursor = await conn.execute(
                    """UPDATE outbox_actions SET status = 'unknown',
                       unknown_since = now(), claimed_at = NULL,
                       last_error_code = 'worker_lost'
                       WHERE status = 'sending'
                         AND claimed_at < now() - %s * interval '1 second'
                       RETURNING id, operation_id, attempt_count""",
                    (older_than_seconds,),
                )
                rows = await cursor.fetchall()
                for action_id, operation_id, attempt in rows:
                    await conn.execute(
                        """UPDATE operations SET status = 'DELIVERY_UNKNOWN',
                           failure_code = 'worker_lost' WHERE id = %s""",
                        (operation_id,),
                    )
                    await conn.execute(
                        """INSERT INTO dispatch_attempts
                           (outbox_id, attempt_number, result)
                           VALUES (%s, %s, 'unknown')
                           ON CONFLICT (outbox_id, attempt_number) DO NOTHING""",
                        (action_id, attempt),
                    )
                    await conn.execute(
                        """INSERT INTO audit_events
                           (id, tenant_id, operation_id, event_type, trace_id, metadata)
                           SELECT %s, tenant_id, id, 'dispatch.unknown', trace_id,
                                  %s FROM operations WHERE id = %s""",
                        (uuid4(), Jsonb({"reason": "worker_lost"}), operation_id),
                    )
                return len(rows)

    async def reconcile(
        self,
        actor: Actor,
        action_id: UUID,
        *,
        sent: bool,
        evidence: str,
        receipt_id: str | None = None,
    ) -> None:
        if actor.role != "admin":
            raise PermissionError("Admin role required")
        if not evidence.strip() or (sent and not receipt_id):
            raise ValueError("Reconciliation requires evidence and a receipt when sent")
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.transaction():
                cursor = await conn.execute(
                    """SELECT a.operation_id, o.trace_id FROM outbox_actions a
                       JOIN operations o ON o.id = a.operation_id
                       WHERE a.id = %s AND o.tenant_id = %s AND a.status = 'unknown'
                       FOR UPDATE OF a""",
                    (action_id, actor.tenant_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise LookupError("Unknown action not found")
                operation_id, trace_id = row
                await conn.execute(
                    """UPDATE outbox_actions SET status = %s, provider_receipt_id = %s,
                       unknown_since = NULL, last_error_code = NULL,
                       next_attempt_at = NULL WHERE id = %s""",
                    ("sent" if sent else "pending", receipt_id, action_id),
                )
                await conn.execute(
                    """UPDATE operations SET status = %s, failure_code = NULL
                       WHERE id = %s""",
                    ("COMPLETED" if sent else "APPROVED", operation_id),
                )
                await conn.execute(
                    """INSERT INTO audit_events
                       (id, tenant_id, operation_id, actor_id, event_type, trace_id, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        uuid4(),
                        actor.tenant_id,
                        operation_id,
                        actor.user_id,
                        "dispatch.reconciled",
                        trace_id,
                        Jsonb(
                            {
                                "sent": sent,
                                "evidence": evidence,
                                "receipt_id": receipt_id,
                            }
                        ),
                    ),
                )
