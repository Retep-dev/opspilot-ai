"""Administrative writer for the persisted local customer dataset."""

from typing import Literal
from uuid import UUID

import psycopg
from pydantic import BaseModel, Field


class CustomerAccountInput(BaseModel):
    customer_id: str = Field(min_length=1, max_length=128)
    account_status: Literal["active", "past_due", "suspended", "closed"]


class CustomerAccountStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    async def upsert(self, tenant_id: UUID, account: CustomerAccountInput) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute(
                """INSERT INTO customer_accounts
                   (tenant_id, customer_id, account_status)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (tenant_id, customer_id) DO UPDATE
                   SET account_status = EXCLUDED.account_status, updated_at = now()""",
                (tenant_id, account.customer_id, account.account_status),
            )
