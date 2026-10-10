import json
import logging
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.observability import log_event


def test_request_id_header_and_safe_structured_fields(caplog) -> None:
    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            response = client.get("/health")
        UUID(response.headers["X-Request-ID"])
        log_event(
            logging.getLogger("opspilot.test"),
            "dispatch.sent",
            tenant_id="tenant-1",
            workflow_thread_id="thread-1",
            provider_attempt_id="attempt-1",
            external_receipt_id="receipt-1",
            retry_count=2,
        )
    event = json.loads(caplog.records[-1].message)
    assert event == {
        "event": "dispatch.sent",
        "tenant_id": "tenant-1",
        "workflow_thread_id": "thread-1",
        "provider_attempt_id": "attempt-1",
        "external_receipt_id": "receipt-1",
        "retry_count": 2,
    }
    assert "Authorization" not in caplog.text
