from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Host-local settings must be loaded before the Compose-oriented .env. Neither
# file overrides variables explicitly exported by the caller.
load_dotenv(".env.local", override=False)
load_dotenv(override=False)


def _env(primary: str, legacy: str | None = None, default: str = "") -> str:
    value = os.getenv(primary)
    if value is None and legacy:
        value = os.getenv(legacy)
    return default if value is None else value


def _bool(primary: str, default: bool, legacy: str | None = None) -> bool:
    raw = _env(primary, legacy, "true" if default else "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv(primary: str, default: str = "", legacy: str | None = None) -> tuple[str, ...]:
    raw = _env(primary, legacy, default)
    return tuple(item.strip().rstrip("/") for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """Runtime settings with TWINSTUDIO_* names and LPS_* compatibility fallbacks."""

    host: str = _env("TWINSTUDIO_HOST", "LPS_HOST", "0.0.0.0")
    port: int = int(_env("TWINSTUDIO_PORT", "LPS_PORT", "8000"))
    public_url: str = _env(
        "TWINSTUDIO_PUBLIC_URL", "LPS_PUBLIC_URL", "http://localhost:8000"
    ).rstrip("/")
    build_sha: str = _env("TWINSTUDIO_BUILD_SHA", default="unknown").strip() or "unknown"
    project_root: Path = Path(_env("TWINSTUDIO_PROJECT_ROOT", default=".")).resolve()
    data_dir: Path = Path(_env("TWINSTUDIO_DATA_DIR", "LPS_DATA_DIR", "./data")).resolve()
    kicad_root: Path = Path(
        _env("TWINSTUDIO_KICAD_ROOT", default=str(project_root))
    ).resolve()
    database_url: str = _env("DATABASE_URL", default="sqlite:///./data/twinstudio.db")

    dev_auth_bypass: bool = _bool("DEV_AUTH_BYPASS", True)
    dev_user_email: str = _env("DEV_USER_EMAIL", default="creator@example.test").lower()
    jwt_secret: str = _env("JWT_SECRET", default="development-only-change-me-please")
    invitation_ttl_hours: int = int(_env("INVITATION_TTL_HOURS", default="48"))
    session_ttl_hours: int = int(_env("SESSION_TTL_HOURS", default="24"))

    smtp_host: str = _env("SMTP_HOST")
    smtp_port: int = int(_env("SMTP_PORT", default="1025"))
    smtp_from: str = _env("SMTP_FROM", default="twinstudio@example.test")
    smtp_username: str = _env("SMTP_USERNAME")
    smtp_password: str = _env("SMTP_PASSWORD")
    smtp_tls: bool = _bool("SMTP_TLS", False)

    mqtt_enabled: bool = _bool("MQTT_ENABLED", False)
    mqtt_host: str = _env("MQTT_HOST", default="localhost")
    mqtt_port: int = int(_env("MQTT_PORT", default="1883"))
    mqtt_username: str = _env("MQTT_USERNAME")
    mqtt_password: str = _env("MQTT_PASSWORD")
    mqtt_topic_prefix: str = _env("MQTT_TOPIC_PREFIX", default="twinstudio/v1").strip("/")

    cad_regeneration_enabled: bool = _bool("TWINSTUDIO_CAD_REGEN_ENABLED", True)

    litellm_model: str = _env("LITELLM_MODEL").strip()
    litellm_api_base: str = _env("LITELLM_API_BASE").strip()
    litellm_api_key: str = _env("LITELLM_API_KEY").strip()

    subllm_enabled: bool = _bool("TWINSTUDIO_SUBLLM_ENABLED", True)
    subllm_application: str = _env("TWINSTUDIO_SUBLLM_APPLICATION", default="twinstudio").strip()
    subllm_function: str = _env("TWINSTUDIO_SUBLLM_FUNCTION", default="eda-nl2dsl").strip()

    mcp_allowed_origins: tuple[str, ...] = _csv(
        "MCP_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000",
    )

    artifact_backend: str = _env("ARTIFACT_BACKEND", default="local")
    export_extension: str = _env("TWINSTUDIO_EXPORT_EXTENSION", default=".twinstudio.zip")

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "outbox" / "emails").mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
