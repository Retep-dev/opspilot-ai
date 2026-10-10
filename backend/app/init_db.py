"""Initialize business schema and LangGraph checkpoint tables."""

import asyncio
import os
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


async def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        await conn.execute(schema)
    async with AsyncPostgresSaver.from_conn_string(database_url) as checkpointer:
        await checkpointer.setup()


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
