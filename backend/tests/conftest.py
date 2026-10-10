"""Use an event loop compatible with psycopg async connections on Windows."""

import asyncio
import os

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
