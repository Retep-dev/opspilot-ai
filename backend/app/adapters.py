"""Provider contracts and a read-only customer-data test adapter."""

from dataclasses import dataclass
from typing import Protocol

import psycopg


@dataclass(frozen=True)
class CustomerRecord:
    customer_id: str
    account_status: str


class CustomerDataAdapter(Protocol):
    async def get_customer(
        self, tenant_id: str, customer_id: str
    ) -> CustomerRecord | None: ...


class MockCustomerDataAdapter:
    def __init__(self, records: dict[str, CustomerRecord] | None = None) -> None:
        self._records = records or {}

    async def get_customer(
        self, tenant_id: str, customer_id: str
    ) -> CustomerRecord | None:
        return self._records.get(customer_id)


class PostgresCustomerDataAdapter:
    """Read-only customer tool; tenant scope is mandatory."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    async def get_customer(
        self, tenant_id: str, customer_id: str
    ) -> CustomerRecord | None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cursor = await conn.execute(
                """SELECT customer_id, account_status FROM customer_accounts
                   WHERE tenant_id = %s AND customer_id = %s""",
                (tenant_id, customer_id),
            )
            row = await cursor.fetchone()
        return CustomerRecord(*row) if row else None


class SlackAdapter(Protocol):
    async def send_message(
        self, channel: str, text: str, idempotency_key: str
    ) -> str: ...


class EmailAdapter(Protocol):
    async def send_email(
        self, recipient: str, subject: str, body: str, idempotency_key: str
    ) -> str: ...
