"""Allowlisted structured event logging without request content or credentials."""

import json
import logging
from contextvars import ContextVar, Token
from uuid import uuid4

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)


def start_request() -> Token:
    return _request_id.set(str(uuid4()))


def end_request(token: Token) -> None:
    _request_id.reset(token)
    _tenant_id.set(None)


def set_tenant(tenant_id: str) -> None:
    _tenant_id.set(tenant_id)


def current_request_id() -> str | None:
    return _request_id.get()


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    tenant_id: str | None = None,
    workflow_thread_id: str | None = None,
    provider_attempt_id: str | None = None,
    external_receipt_id: str | None = None,
    retry_count: int | None = None,
    request_id: str | None = None,
) -> None:
    record = {
        "event": event,
        "request_id": request_id or _request_id.get(),
        "tenant_id": tenant_id or _tenant_id.get(),
        "workflow_thread_id": workflow_thread_id,
        "provider_attempt_id": provider_attempt_id,
        "external_receipt_id": external_receipt_id,
        "retry_count": retry_count,
    }
    logger.info(
        json.dumps({key: value for key, value in record.items() if value is not None})
    )
