from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from twinstudio.domain import EventEnvelope, Role

metadata = MetaData()

events_table = Table(
    "events",
    metadata,
    Column("event_id", String(64), primary_key=True),
    Column("stream_id", String(255), nullable=False, index=True),
    Column("stream_version", Integer, nullable=False),
    Column("event_type", String(128), nullable=False, index=True),
    Column("data", JSON, nullable=False),
    Column("actor", String(320), nullable=False),
    Column("correlation_id", String(64)),
    Column("causation_id", String(64)),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("schema_version", Integer, nullable=False, default=1),
    UniqueConstraint("stream_id", "stream_version", name="uq_stream_version"),
)

users_table = Table(
    "users",
    metadata,
    Column("email", String(320), primary_key=True),
    Column("display_name", String(160)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("disabled_at", DateTime(timezone=True)),
)

api_tokens_table = Table(
    "api_tokens",
    metadata,
    Column("token_id", String(64), primary_key=True),
    Column("email", String(320), nullable=False, index=True),
    Column("token_hash", String(128), nullable=False, unique=True),
    Column("label", String(120), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)

sessions_table = Table(
    "sessions",
    metadata,
    Column("session_id", String(64), primary_key=True),
    Column("email", String(320), nullable=False, index=True),
    Column("token_hash", String(128), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
)

invitations_table = Table(
    "invitations",
    metadata,
    Column("invitation_id", String(64), primary_key=True),
    Column("project_id", String(160), nullable=False, index=True),
    Column("requested_email", String(320), nullable=False),
    Column("requested_role", String(32), nullable=False),
    Column("requested_by", String(320), nullable=False),
    Column("approver_email", String(320), nullable=False),
    Column("message", Text, nullable=False, default=""),
    Column("status", String(32), nullable=False),
    Column("approval_token_hash", String(128), nullable=False, unique=True),
    Column("access_token_hash", String(128), unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("approved_at", DateTime(timezone=True)),
    Column("accepted_at", DateTime(timezone=True)),
)


class ConcurrencyError(RuntimeError):
    pass


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class EventStore:
    def __init__(self, database_url: str):
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
        metadata.create_all(self.engine)

    def current_version(self, stream_id: str) -> int:
        with self.engine.connect() as conn:
            value = conn.execute(
                select(func.max(events_table.c.stream_version)).where(events_table.c.stream_id == stream_id)
            ).scalar_one_or_none()
            return int(value or 0)

    def append(
        self,
        stream_id: str,
        expected_version: int | None,
        new_events: Iterable[EventEnvelope],
    ) -> list[EventEnvelope]:
        materialized = list(new_events)
        if not materialized:
            return []
        try:
            with self.engine.begin() as conn:
                current = conn.execute(
                    select(func.max(events_table.c.stream_version)).where(events_table.c.stream_id == stream_id)
                ).scalar_one_or_none()
                current_version = int(current or 0)
                if expected_version is not None and expected_version != current_version:
                    raise ConcurrencyError(
                        f"Stream {stream_id!r} is at version {current_version}, expected {expected_version}"
                    )
                stored: list[EventEnvelope] = []
                for offset, event in enumerate(materialized, start=1):
                    version = current_version + offset
                    normalized = event.model_copy(update={"stream_id": stream_id, "stream_version": version})
                    conn.execute(
                        insert(events_table).values(
                            event_id=normalized.event_id,
                            stream_id=stream_id,
                            stream_version=version,
                            event_type=normalized.event_type,
                            data=normalized.data,
                            actor=normalized.actor,
                            correlation_id=normalized.correlation_id,
                            causation_id=normalized.causation_id,
                            occurred_at=normalized.occurred_at,
                            schema_version=normalized.schema_version,
                        )
                    )
                    stored.append(normalized)
                return stored
        except IntegrityError as exc:
            raise ConcurrencyError(f"Concurrent write to stream {stream_id!r}") from exc

    def load(self, stream_id: str, *, after_version: int = 0) -> list[EventEnvelope]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(events_table)
                .where(events_table.c.stream_id == stream_id)
                .where(events_table.c.stream_version > after_version)
                .order_by(events_table.c.stream_version)
            ).mappings()
            return [EventEnvelope.model_validate(dict(row)) for row in rows]

    def list_streams(self, *, limit: int = 100) -> list[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(events_table.c.stream_id)
                .distinct()
                .order_by(events_table.c.stream_id)
                .limit(limit)
            )
            return [str(row[0]) for row in rows]

    def delete_stream(self, stream_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(events_table).where(events_table.c.stream_id == stream_id))

    def ensure_user(self, email: str, display_name: str | None = None) -> None:
        normalized = email.lower()
        with self.engine.begin() as conn:
            exists = conn.execute(select(users_table.c.email).where(users_table.c.email == normalized)).first()
            if not exists:
                conn.execute(
                    insert(users_table).values(
                        email=normalized,
                        display_name=display_name,
                        created_at=datetime.now(UTC),
                    )
                )

    def create_api_token(
        self,
        email: str,
        *,
        label: str = "API token",
        expires_at: datetime | None = None,
    ) -> tuple[str, str]:
        self.ensure_user(email)
        raw = secrets.token_urlsafe(36)
        token_id = secrets.token_hex(16)
        with self.engine.begin() as conn:
            conn.execute(
                insert(api_tokens_table).values(
                    token_id=token_id,
                    email=email.lower(),
                    token_hash=token_hash(raw),
                    label=label,
                    created_at=datetime.now(UTC),
                    expires_at=expires_at,
                )
            )
        return token_id, raw

    def authenticate_api_token(self, email: str, raw_token: str) -> bool:
        now = datetime.now(UTC)
        with self.engine.connect() as conn:
            row = conn.execute(
                select(api_tokens_table)
                .where(api_tokens_table.c.email == email.lower())
                .where(api_tokens_table.c.token_hash == token_hash(raw_token))
                .where(api_tokens_table.c.revoked_at.is_(None))
            ).mappings().first()
            if not row:
                return False
            expires_at = row["expires_at"]
            if expires_at is not None and _aware(expires_at) <= now:
                return False
            return True

    def create_session(self, email: str, expires_at: datetime) -> str:
        self.ensure_user(email)
        raw = secrets.token_urlsafe(40)
        with self.engine.begin() as conn:
            conn.execute(
                insert(sessions_table).values(
                    session_id=secrets.token_hex(16),
                    email=email.lower(),
                    token_hash=token_hash(raw),
                    created_at=datetime.now(UTC),
                    expires_at=expires_at,
                )
            )
        return raw

    def authenticate_session(self, raw_token: str) -> str | None:
        now = datetime.now(UTC)
        with self.engine.connect() as conn:
            row = conn.execute(
                select(sessions_table)
                .where(sessions_table.c.token_hash == token_hash(raw_token))
                .where(sessions_table.c.revoked_at.is_(None))
            ).mappings().first()
            if not row or _aware(row["expires_at"]) <= now:
                return None
            return str(row["email"])

    def create_invitation(
        self,
        *,
        project_id: str,
        requested_email: str,
        requested_role: Role,
        requested_by: str,
        approver_email: str,
        message: str,
        expires_at: datetime,
    ) -> tuple[str, str, str]:
        invitation_id = secrets.token_hex(16)
        approval_token = secrets.token_urlsafe(40)
        with self.engine.begin() as conn:
            conn.execute(
                insert(invitations_table).values(
                    invitation_id=invitation_id,
                    project_id=project_id,
                    requested_email=requested_email.lower(),
                    requested_role=requested_role.value,
                    requested_by=requested_by.lower(),
                    approver_email=approver_email.lower(),
                    message=message,
                    status="pending_approval",
                    approval_token_hash=token_hash(approval_token),
                    created_at=datetime.now(UTC),
                    expires_at=expires_at,
                )
            )
        return invitation_id, approval_token, requested_email.lower()

    def approve_invitation(self, approval_token: str) -> tuple[dict, str]:
        now = datetime.now(UTC)
        access_token = secrets.token_urlsafe(40)
        with self.engine.begin() as conn:
            row = conn.execute(
                select(invitations_table).where(
                    invitations_table.c.approval_token_hash == token_hash(approval_token)
                )
            ).mappings().first()
            if not row:
                raise ValueError("Invitation approval token is invalid")
            if row["status"] != "pending_approval":
                raise ValueError(f"Invitation is already {row['status']}")
            if _aware(row["expires_at"]) <= now:
                raise ValueError("Invitation has expired")
            conn.execute(
                update(invitations_table)
                .where(invitations_table.c.invitation_id == row["invitation_id"])
                .values(
                    status="approved",
                    approved_at=now,
                    access_token_hash=token_hash(access_token),
                )
            )
            result = dict(row)
            result["status"] = "approved"
            result["approved_at"] = now
            return result, access_token

    def reject_invitation(self, approval_token: str) -> dict:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(invitations_table).where(
                    invitations_table.c.approval_token_hash == token_hash(approval_token)
                )
            ).mappings().first()
            if not row:
                raise ValueError("Invitation approval token is invalid")
            conn.execute(
                update(invitations_table)
                .where(invitations_table.c.invitation_id == row["invitation_id"])
                .values(status="rejected")
            )
            result = dict(row)
            result["status"] = "rejected"
            return result

    def accept_invitation(self, access_token: str) -> dict:
        now = datetime.now(UTC)
        with self.engine.begin() as conn:
            row = conn.execute(
                select(invitations_table).where(
                    invitations_table.c.access_token_hash == token_hash(access_token)
                )
            ).mappings().first()
            if not row:
                raise ValueError("Invitation access token is invalid")
            if row["status"] != "approved":
                raise ValueError(f"Invitation cannot be accepted in state {row['status']}")
            if _aware(row["expires_at"]) <= now:
                raise ValueError("Invitation has expired")
            conn.execute(
                update(invitations_table)
                .where(invitations_table.c.invitation_id == row["invitation_id"])
                .values(status="accepted", accepted_at=now)
            )
            result = dict(row)
            result["status"] = "accepted"
            result["accepted_at"] = now
            return result


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
