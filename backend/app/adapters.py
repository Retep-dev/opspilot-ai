"""Provider contracts and a read-only customer-data test adapter."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CustomerRecord:
    customer_id: str
    account_status: str


class CustomerDataAdapter(Protocol):
    async def get_customer(self, customer_id: str) -> CustomerRecord | None: ...


class MockCustomerDataAdapter:
    def __init__(self, records: dict[str, CustomerRecord] | None = None) -> None:
        self._records = records or {}

    async def get_customer(self, customer_id: str) -> CustomerRecord | None:
        return self._records.get(customer_id)


class SlackAdapter(Protocol):
    async def send_message(
        self, channel: str, text: str, idempotency_key: str
    ) -> str: ...


class EmailAdapter(Protocol):
    async def send_email(
        self, recipient: str, subject: str, body: str, idempotency_key: str
    ) -> str: ...
