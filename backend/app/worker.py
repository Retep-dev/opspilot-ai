"""Run the outbox dispatcher as a separate process."""

import asyncio
import logging
import os

from app.outbox import OutboxDispatcher
from app.providers import LiveTestGuard, ResendEmailProvider, SlackProvider

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    slack = SlackProvider(os.environ["SLACK_BOT_TOKEN"])
    email = ResendEmailProvider(os.environ["RESEND_API_KEY"], os.environ["EMAIL_FROM"])
    providers = {"slack": slack, "email": email}
    if os.getenv("OPSPILOT_LIVE_TEST_MODE") == "true":
        providers = {
            "slack": LiveTestGuard(slack, os.environ["SLACK_TEST_CHANNEL_ID"]),
            "email": LiveTestGuard(email, os.environ["TEST_RECIPIENT_EMAIL"]),
        }
    dispatcher = OutboxDispatcher(database_url, providers)
    try:
        while True:
            stale = await dispatcher.mark_stale_unknown()
            if stale:
                logger.warning(
                    "quarantined stale delivery attempts", extra={"count": stale}
                )
            if not await dispatcher.run_once():
                await asyncio.sleep(2)
    finally:
        await slack.close()
        await email.close()


if __name__ == "__main__":
    asyncio.run(main())
