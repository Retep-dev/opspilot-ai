from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth import get_actor
from app.main import app, get_customer_store, get_ingestor, get_service
from app.service import Actor


class FakeService:
    async def create(self, actor, payload):
        return uuid4()

    async def decide(self, actor, operation_id, decision):
        return None


class FakeIngestor:
    async def ingest(self, tenant_id, document):
        return uuid4()


class FakeCustomerStore:
    async def upsert(self, tenant_id, account):
        return None


def test_api_enforces_requester_reviewer_admin_roles() -> None:
    tenant_id, user_id = uuid4(), uuid4()
    app.dependency_overrides[get_service] = lambda: FakeService()
    app.dependency_overrides[get_ingestor] = lambda: FakeIngestor()
    app.dependency_overrides[get_customer_store] = lambda: FakeCustomerStore()
    app.dependency_overrides[get_actor] = lambda: Actor(user_id, tenant_id, "requester")
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    "/operations", json={"request_text": "Check case"}
                ).status_code
                == 201
            )
            operation_id = uuid4()
            assert (
                client.post(
                    f"/operations/{operation_id}/decision",
                    json={"decision": "approved", "draft_hash": "hash"},
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/knowledge/documents",
                    json={
                        "source": "runbook",
                        "content": "text",
                        "ingestion_version": 1,
                    },
                ).status_code
                == 403
            )
            assert (
                client.put(
                    "/customer-accounts/c-1",
                    json={"customer_id": "c-1", "account_status": "active"},
                ).status_code
                == 403
            )
            app.dependency_overrides[get_actor] = lambda: Actor(
                user_id, tenant_id, "reviewer"
            )
            assert (
                client.post(
                    f"/operations/{operation_id}/decision",
                    json={"decision": "approved", "draft_hash": "hash"},
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/knowledge/documents",
                    json={
                        "source": "runbook",
                        "content": "text",
                        "ingestion_version": 1,
                    },
                ).status_code
                == 403
            )
            app.dependency_overrides[get_actor] = lambda: Actor(
                user_id, tenant_id, "admin"
            )
            assert (
                client.post(
                    "/knowledge/documents",
                    json={
                        "source": "runbook",
                        "content": "text",
                        "ingestion_version": 1,
                    },
                ).status_code
                == 201
            )
            assert (
                client.put(
                    "/customer-accounts/c-1",
                    json={"customer_id": "c-1", "account_status": "active"},
                ).status_code
                == 200
            )
    finally:
        app.dependency_overrides.clear()
