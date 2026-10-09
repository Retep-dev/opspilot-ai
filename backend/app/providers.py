"""Slack and Resend delivery adapters with explicit outcome classification."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.models import ActionDraft


@dataclass(frozen=True)
class Receipt:
    provider_id: str


class RetryableDeliveryError(Exception):
    pass


class PermanentDeliveryError(Exception):
    pass


class UnknownDeliveryOutcome(Exception):
    pass


class SlackProvider:
    def __init__(self, token: str, client: httpx.AsyncClient | None = None) -> None:
        self.token = token
        self.client = client or httpx.AsyncClient(timeout=15)
        self.owns_client = client is None

    async def close(self) -> None:
        if self.owns_client:
            await self.client.aclose()

    async def send(self, draft: ActionDraft, key: str) -> Receipt:
        if draft.provider != "slack":
            raise ValueError("Wrong provider")
        try:
            response = await self.client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "channel": draft.destination,
                    "text": draft.body,
                    "client_msg_id": str(uuid5(NAMESPACE_URL, key)),
                },
            )
        except httpx.TransportError as error:
            raise UnknownDeliveryOutcome("slack_transport_uncertain") from error
        if response.status_code == 429:
            raise RetryableDeliveryError("slack_rate_limited")
        if response.status_code >= 500:
            raise UnknownDeliveryOutcome("slack_server_uncertain")
        if response.status_code >= 400:
            raise PermanentDeliveryError(f"slack_http_{response.status_code}")
        data = response.json()
        if not data.get("ok"):
            code = data.get("error", "slack_rejected")
            if code == "ratelimited":
                raise RetryableDeliveryError(code)
            if code in {"internal_error", "fatal_error"}:
                raise UnknownDeliveryOutcome(code)
            raise PermanentDeliveryError(code)
        return Receipt(provider_id=f"{data['channel']}:{data['ts']}")


class ResendEmailProvider:
    def __init__(
        self, api_key: str, from_address: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self.api_key = api_key
        self.from_address = from_address
        self.client = client or httpx.AsyncClient(timeout=15)
        self.owns_client = client is None

    async def close(self) -> None:
        if self.owns_client:
            await self.client.aclose()

    async def send(self, draft: ActionDraft, key: str) -> Receipt:
        if draft.provider != "email":
            raise ValueError("Wrong provider")
        if not draft.subject:
            raise PermanentDeliveryError("email_subject_required")
        try:
            response = await self.client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Idempotency-Key": key,
                },
                json={
                    "from": self.from_address,
                    "to": [draft.destination],
                    "subject": draft.subject,
                    "text": draft.body,
                },
            )
        except httpx.TransportError as error:
            raise UnknownDeliveryOutcome("email_transport_uncertain") from error
        if response.status_code == 429:
            raise RetryableDeliveryError(f"email_http_{response.status_code}")
        if response.status_code >= 500:
            raise UnknownDeliveryOutcome(f"email_http_{response.status_code}")
        if response.status_code == 409:
            code = response.json().get("name", "email_conflict")
            if code == "concurrent_idempotent_requests":
                raise RetryableDeliveryError(code)
            raise PermanentDeliveryError(code)
        if response.status_code >= 400:
            raise PermanentDeliveryError(f"email_http_{response.status_code}")
        return Receipt(provider_id=response.json()["id"])
