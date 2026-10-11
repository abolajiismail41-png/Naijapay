from app.core.config import Settings
from app.modules.fraud.service import evaluate_signals


def settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://test:test@localhost/test", redis_url="redis://localhost:6379/0",
                    jwt_secret="j" * 32, encryption_key="e" * 32, webhook_secret="w" * 32,
                    fraud_high_value_kobo=5_000_000, fraud_unverified_value_kobo=2_000_000,
                    fraud_velocity_window_min=10, fraud_velocity_count=5)


def test_low_value_verified_transaction_has_no_signals():
    assert evaluate_signals(10_000, True, 1, settings()) == []


def test_high_value_unverified_and_velocity_signals_are_review_only_rules():
    rules = evaluate_signals(5_000_000, False, 10, settings())
    assert {r[0] for r in rules} == {"HIGH_VALUE", "UNVERIFIED_HIGH_VALUE", "TRANSACTION_VELOCITY"}
    assert all(r[2] <= 100 for r in rules)
