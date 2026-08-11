from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip().rstrip("/") for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("LPS_HOST", "0.0.0.0")
    port: int = int(os.getenv("LPS_PORT", "8000"))
    public_url: str = os.getenv("LPS_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    data_dir: Path = Path(os.getenv("LPS_DATA_DIR", "./data")).resolve()
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/lps.db")

    dev_auth_bypass: bool = _bool("DEV_AUTH_BYPASS", True)
    dev_user_email: str = os.getenv("DEV_USER_EMAIL", "creator@example.test").lower()
    jwt_secret: str = os.getenv("JWT_SECRET", "development-only-change-me-please")
    invitation_ttl_hours: int = int(os.getenv("INVITATION_TTL_HOURS", "48"))
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "24"))

    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "1025"))
    smtp_from: str = os.getenv("SMTP_FROM", "lps@example.test")
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_tls: bool = _bool("SMTP_TLS", False)

    mqtt_enabled: bool = _bool("MQTT_ENABLED", False)
    mqtt_host: str = os.getenv("MQTT_HOST", "localhost")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_username: str = os.getenv("MQTT_USERNAME", "")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    mqtt_topic_prefix: str = os.getenv("MQTT_TOPIC_PREFIX", "lps/v1").strip("/")

    litellm_model: str = os.getenv("LITELLM_MODEL", "").strip()
    litellm_api_base: str = os.getenv("LITELLM_API_BASE", "").strip()
    litellm_api_key: str = os.getenv("LITELLM_API_KEY", "").strip()

    mcp_allowed_origins: tuple[str, ...] = _csv(
        "MCP_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000",
    )

    artifact_backend: str = os.getenv("ARTIFACT_BACKEND", "local")

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "outbox" / "emails").mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
