from decimal import Decimal
from enum import StrEnum
from typing import Literal
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


_MIN_SECRET_LEN = 32
_PLACEHOLDER_MARKERS = ("change-me", "changeme", "placeholder")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"
    app_name: str = "naijapay"

    database_url: str
    db_pool_size: int = Field(10, ge=1)
    db_max_overflow: int = Field(10, ge=0)
    db_pool_timeout_s: int = Field(10, ge=1)
    redis_url: str

    jwt_secret: SecretStr
    encryption_key: SecretStr
    webhook_secret: SecretStr

    access_token_ttl_min: int = Field(10, ge=1)
    refresh_token_ttl_days: int = Field(30, ge=1)
    otp_ttl_min: int = Field(10, ge=1)
    step_up_ttl_s: int = Field(120, ge=30)

    payment_processor: Literal["paystack", "sandbox"] = "sandbox"
    paystack_secret_key: SecretStr = SecretStr("")
    paystack_callback_url: str | None = None
    payment_email_domain: str = "pay.naijapay.example"  # Paystack needs an email; we only hold phones
    funding_min_kobo: int = Field(50_000, ge=1)          # NGN 500
    funding_max_kobo: int = Field(200_000_000, ge=1)     # NGN 2,000,000
    funding_fee_percent: Decimal = Decimal("1.5")
    funding_fee_flat_kobo: int = Field(10_000, ge=0)
    funding_fee_flat_waived_below_kobo: int = Field(250_000, ge=0)
    funding_fee_cap_kobo: int = Field(200_000, ge=0)
    funding_poll_verify_after_s: int = Field(10, ge=0)
    funding_open_ttl_h: int = Field(24, ge=1)

    bill_provider: Literal["inlomax", "sandbox"] = "sandbox"
    inlomax_api_key: SecretStr = SecretStr("")
    inlomax_base_url: str = "https://inlomax.com/api"   # sandbox: https://inlomax.com/sandbox
    inlomax_webhook_token: SecretStr = SecretStr("")    # secret path segment: Inlomax webhooks are unsigned
    inlomax_float_alert_kobo: int = Field(5_000_000, ge=0)
    airtime_min_kobo: int = Field(5_000, ge=100)         # NGN 50 (placeholder: confirm with Inlomax)
    airtime_max_kobo: int = Field(5_000_000, ge=100)     # NGN 50,000 (placeholder)
    electricity_min_kobo: int = Field(50_000, ge=100)         # NGN 500 (placeholder)
    electricity_max_kobo: int = Field(10_000_000, ge=100)     # NGN 100,000 (placeholder)
    inlomax_electricity_enabled: bool = False                  # off until the adapter is verified against their sandbox
    inlomax_tv_enabled: bool = False                           # off until smartcard + purchase mappings are verified
    inlomax_meter_verify_path: str = "/validatemeter"          # UNVERIFIED path
    inlomax_electricity_path: str = "/electricity"             # UNVERIFIED path
    meter_validation_ttl_s: int = Field(900, ge=60)
    education_max_quantity: int = Field(5, ge=1, le=20)
    provider_cost_max_age_h: int = Field(72, ge=1)
    unsent_refund_after_min: int = Field(10, ge=1)

    # Optional notification transports. Unconfigured channels are never reported as delivered.
    smtp_host: str | None = None
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr = SecretStr("")
    smtp_from_email: str | None = None
    smtp_starttls: bool = True
    termii_api_key: SecretStr = SecretStr("")
    termii_sender_id: str | None = None
    termii_base_url: str = "https://api.ng.termii.com"
    notification_max_attempts: int = Field(8, ge=1, le=20)

    # Set to a positive amount to enable referral payouts; zero keeps the program non-paying.
    referral_reward_kobo: int = Field(0, ge=0, le=10_000_000)
    referral_min_purchase_kobo: int = Field(50_000, ge=0, le=200_000_000)

    # Fraud rules create review cases only; they never automatically freeze or reverse money.
    fraud_high_value_kobo: int = Field(5_000_000, ge=1)
    fraud_unverified_value_kobo: int = Field(2_000_000, ge=1)
    fraud_velocity_window_min: int = Field(10, ge=1, le=1440)
    fraud_velocity_count: int = Field(5, ge=2, le=100)

    cors_origins: list[str] = []
    max_request_bytes: int = Field(1_048_576, ge=1024)

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @model_validator(mode="after")
    def _reject_weak_secrets_outside_local(self) -> "Settings":
        if self.smtp_username and not self.smtp_starttls:
            raise ValueError("SMTP credentials require STARTTLS")
        if self.environment in (Environment.LOCAL, Environment.TEST):
            return self
        for name in ("jwt_secret", "encryption_key", "webhook_secret"):
            value = getattr(self, name).get_secret_value()
            if len(value) < _MIN_SECRET_LEN or any(m in value.lower() for m in _PLACEHOLDER_MARKERS):
                raise ValueError(f"{name} is too weak or still a placeholder")
        if self.payment_processor != "paystack" or not self.paystack_secret_key.get_secret_value().startswith("sk_"):
            raise ValueError("production-like environments require PAYMENT_PROCESSOR=paystack and a Paystack secret key")
        if (self.bill_provider != "inlomax" or not self.inlomax_api_key.get_secret_value()
                or len(self.inlomax_webhook_token.get_secret_value()) < _MIN_SECRET_LEN):
            raise ValueError("production-like environments require BILL_PROVIDER=inlomax, an API key and a webhook token")
        if "*" in self.cors_origins:
            raise ValueError("wildcard CORS is not allowed outside local/test")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
