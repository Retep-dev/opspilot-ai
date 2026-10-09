from app.outbox import backoff_seconds


def test_backoff_is_stable_and_bounded() -> None:
    assert backoff_seconds(1, "key") == backoff_seconds(1, "key")
    assert backoff_seconds(2, "key") >= backoff_seconds(1, "key")
    assert backoff_seconds(100, "key") <= 3605
