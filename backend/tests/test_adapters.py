import asyncio
import json

import httpx
import pytest

from app.models import ActionDraft
from app.nim import NimClient
from app.providers import (
    Receipt,
    ResendEmailProvider,
    SlackProvider,
    UnknownDeliveryOutcome,
)


def test_nim_generation_and_embedding_contracts() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("chat/completions"):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "recommendation": {
                                            "summary": "Review",
                                            "evidence": [],
                                            "uncertainty": "Needs review",
                                            "risk_level": "medium",
                                        },
                                        "draft": {
                                            "provider": "email",
                                            "destination": "ops@example.com",
                                            "subject": "Review",
                                            "body": "Please review",
                                        },
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1024}]})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            nim = NimClient("test-key", "chat-model", "embed-model", client=client)
            generated = await nim.generate("Check case", [], "active")
            assert generated.draft.provider == "email"
            assert len(await nim.embed_query("question")) == 1024
            assert len(await nim.embed_passage("answer")) == 1024
        assert requests[0].headers["authorization"] == "Bearer test-key"
        assert json.loads(requests[1].content)["input_type"] == "query"
        assert json.loads(requests[2].content)["input_type"] == "passage"

    asyncio.run(scenario())


def test_email_idempotency_key_and_slack_receipt() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api.resend.com":
            return httpx.Response(200, json={"id": "email-1"})
        return httpx.Response(200, json={"ok": True, "channel": "C1", "ts": "123.1"})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            email = ResendEmailProvider("test-key", "verified@example.com", client)
            slack = SlackProvider("test-token", client)
            draft = ActionDraft(
                provider="email",
                destination="ops@example.com",
                subject="Case",
                body="Review",
            )
            assert await email.send(draft, "stable-key") == Receipt("email-1")
            assert await email.send(draft, "stable-key") == Receipt("email-1")
            slack_draft = ActionDraft(provider="slack", destination="C1", body="Review")
            assert await slack.send(slack_draft, "stable-key") == Receipt("C1:123.1")
            assert await slack.send(slack_draft, "stable-key") == Receipt("C1:123.1")
        assert requests[0].headers["idempotency-key"] == "stable-key"
        assert requests[1].headers["idempotency-key"] == "stable-key"
        assert (
            json.loads(requests[2].content)["client_msg_id"]
            == json.loads(requests[3].content)["client_msg_id"]
        )

    asyncio.run(scenario())


def test_slack_timeout_is_unknown_not_retried_as_definite_failure() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("uncertain")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            provider = SlackProvider("test-token", client)
            with pytest.raises(UnknownDeliveryOutcome):
                await provider.send(
                    ActionDraft(provider="slack", destination="C1", body="Test"), "key"
                )

    asyncio.run(scenario())
