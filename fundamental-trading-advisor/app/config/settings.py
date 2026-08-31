"""Application configuration.

All settings are loaded from environment variables / a local .env file.
Nothing here is a secret default -- see .env.example. AUTO_EXECUTION is
hardcoded False at the type level (see app.broker.pepperstone) in addition
to being a settings field, so no config change can silently enable it.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RiskProfile:
    CONSERVATIVE = 0.0025
    MODERATE = 0.0050
    AGGRESSIVE_MAX = 0.0100


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM (synthesis/explanation layer only -- never the source of data)
    anthropic_api_key: str | None = Field(default=None)
    anthropic_model: str = Field(default="claude-sonnet-4-5")

    # Optional official-source API keys (free tiers)
    fred_api_key: str | None = Field(default=None)
    eia_api_key: str | None = Field(default=None)

    # Broker / execution safety
    mt5_enabled: bool = Field(default=False)
    auto_execution: bool = Field(default=False)

    # Price provider (V1.1.1: automatic execution-price input, read-only)
    price_provider: str = Field(default="auto")
    max_quote_age_seconds: int = Field(default=60)

    # Paper trading / journal
    paper_trading: bool = Field(default=True)

    # Risk
    account_equity: float | None = Field(default=None)
    risk_percent: float = Field(default=RiskProfile.MODERATE)

    # Locale
    timezone: str = Field(default="America/Costa_Rica")

    # Data
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    cache_dir: Path = Field(default=PROJECT_ROOT / "data" / "cache")
    journal_dir: Path = Field(default=PROJECT_ROOT / "data" / "journal")

    @field_validator("auto_execution")
    @classmethod
    def _auto_execution_must_be_false(cls, v: bool) -> bool:
        if v:
            raise ValueError(
                "AUTO_EXECUTION=true is not supported in this version. "
                "This project is READ / ANALYZE / RECOMMEND / LOG only."
            )
        return v

    @field_validator("price_provider")
    @classmethod
    def _price_provider_must_be_known(cls, v: str) -> str:
        allowed = {"auto", "mt5", "manual"}
        if v not in allowed:
            raise ValueError(f"PRICE_PROVIDER must be one of {sorted(allowed)}, got '{v}'")
        return v

    @field_validator("max_quote_age_seconds")
    @classmethod
    def _max_quote_age_seconds_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("MAX_QUOTE_AGE_SECONDS must be positive")
        return v

    @field_validator("risk_percent")
    @classmethod
    def _risk_percent_bounds(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("RISK_PERCENT must be positive")
        if v > RiskProfile.AGGRESSIVE_MAX:
            raise ValueError(
                f"RISK_PERCENT={v} exceeds the {RiskProfile.AGGRESSIVE_MAX:.2%} "
                "default safety ceiling. Lower it or change the code deliberately."
            )
        return v


def get_settings() -> Settings:
    return Settings()
