import asyncio

from app.adapters import CustomerRecord, MockCustomerDataAdapter


def test_mock_customer_is_read_only() -> None:
    adapter = MockCustomerDataAdapter({"c-1": CustomerRecord("c-1", "active")})
    assert asyncio.run(adapter.get_customer("c-1")) == CustomerRecord("c-1", "active")
    assert asyncio.run(adapter.get_customer("missing")) is None
