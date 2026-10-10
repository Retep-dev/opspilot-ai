"""Opt-in live NIM probe with synthetic inputs and redacted output."""

import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from app.nim import NimClient


async def main() -> None:
    load_dotenv(Path(__file__).parents[2] / ".env", override=False)
    required = ("NVIDIA_NIM_API_KEY", "NVIDIA_CHAT_MODEL", "NVIDIA_EMBEDDING_MODEL")
    if not all(os.getenv(name) for name in required):
        print(json.dumps({"status": "missing_configuration"}))
        raise SystemExit(2)
    client = NimClient(
        os.environ["NVIDIA_NIM_API_KEY"],
        os.environ["NVIDIA_CHAT_MODEL"],
        os.environ["NVIDIA_EMBEDDING_MODEL"],
        chat_base_url=os.getenv(
            "NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"
        ),
        embedding_url=os.getenv(
            "NVIDIA_EMBEDDING_URL",
            "https://integrate.api.nvidia.com/v1/embeddings",
        ),
    )
    phase = "query_embedding"
    try:
        query = await client.embed_query("OpsPilot synthetic account support request")
        phase = "passage_embedding"
        passage = await client.embed_passage(
            "Synthetic runbook: escalate account access concerns for review."
        )
        phase = "generation"
        generated = await client.generate(
            "TEST ONLY: recommend review of a synthetic account request.",
            [{"source": "synthetic-runbook", "excerpt": "Escalate for review."}],
            "active",
        )
        print(
            json.dumps(
                {
                    "status": "verified",
                    "chat_model": client.chat_model,
                    "embedding_model": client.embedding_model,
                    "query_dimensions": len(query),
                    "passage_dimensions": len(passage),
                    "draft_provider": generated.draft.provider,
                }
            )
        )
    except Exception as error:  # noqa: BLE001 - report only safe diagnostics
        details = {
            "status": "failed",
            "phase": phase,
            "error_type": type(error).__name__,
        }
        if isinstance(error, httpx.HTTPStatusError):
            details["http_status"] = error.response.status_code
        if isinstance(error, ValidationError):
            details["validation_issues"] = [
                {"field": ".".join(map(str, issue["loc"])), "type": issue["type"]}
                for issue in error.errors(include_input=False)
            ]
        print(json.dumps(details))
        raise SystemExit(1) from None
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
