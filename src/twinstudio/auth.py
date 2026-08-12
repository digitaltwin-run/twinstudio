from __future__ import annotations

import base64
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

from twinstudio.bus import CommandBus, QueryService
from twinstudio.domain import AuthPrincipal, CommandEnvelope, EventEnvelope, InvitationRequest, Role
from twinstudio.event_store import EventStore
from twinstudio.settings import Settings

if TYPE_CHECKING:
    from twinstudio.mqtt_bus import EventPublisher


@dataclass(slots=True)
class InvitationResult:
    invitation_id: str
    status: str
    approver_email: str
    requested_email: str


class Mailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, to_email: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.smtp_from
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        if not self.settings.smtp_host:
            self._write_outbox(to_email, subject, body)
            return
        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as smtp:
                if self.settings.smtp_tls:
                    smtp.starttls()
                if self.settings.smtp_username:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(message)
        except Exception:
            self._write_outbox(to_email, subject, body)

    def _write_outbox(self, to_email: str, subject: str, body: str) -> None:
        safe = to_email.replace("@", "_at_").replace("/", "_")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.settings.data_dir / "outbox" / "emails" / f"{timestamp}-{safe}.txt"
        path.write_text(f"To: {to_email}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")


class AuthService:
    def __init__(
        self,
        settings: Settings,
        store: EventStore,
        queries: QueryService,
        commands: CommandBus,
        publisher: "EventPublisher",
    ):
        self.settings = settings
        self.store = store
        self.queries = queries
        self.commands = commands
        self.publisher = publisher
        self.mailer = Mailer(settings)

    def principal_from_request(self, request: Request) -> AuthPrincipal:
        if self.settings.dev_auth_bypass:
            return AuthPrincipal(email=self.settings.dev_user_email, auth_method="dev")
        session = request.cookies.get("twinstudio_session") or request.cookies.get("lps_session")
        if session:
            email = self.store.authenticate_session(session)
            if email:
                return AuthPrincipal(email=email, auth_method="session")
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
                email, token = decoded.split(":", 1)
            except Exception as exc:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Basic credentials") from exc
            if self.store.authenticate_api_token(email, token):
                return AuthPrincipal(email=email.lower(), auth_method="basic")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Use a magic-link session or HTTP Basic email:API-token.",
            headers={"WWW-Authenticate": "Basic realm=TwinStudio"},
        )

    def role_for(self, project_id: str, email: str) -> Role | None:
        snapshot = self.queries.project(project_id)
        return snapshot.memberships.get(email.lower())

    def request_access(
        self,
        body: InvitationRequest,
        *,
        requested_by: str | None = None,
        decision_email: str | None = None,
    ) -> InvitationResult:
        snapshot = self.queries.project(body.project_id)
        approvers = [
            email
            for email, role in snapshot.memberships.items()
            if role in {Role.CREATOR, Role.ADMIN}
        ]
        if not approvers:
            raise ValueError("Project has no creator or admin able to approve access")
        if decision_email:
            normalized = decision_email.lower()
            if normalized not in approvers:
                raise ValueError("Decision email is not a creator/admin member of this project")
            approver = normalized
        else:
            creators = [email for email in approvers if snapshot.memberships[email] == Role.CREATOR]
            approver = creators[0] if creators else approvers[0]
        requester = (requested_by or body.requested_email).lower()
        expires_at = datetime.now(UTC) + timedelta(hours=self.settings.invitation_ttl_hours)
        invitation_id, approval_token, requested_email = self.store.create_invitation(
            project_id=body.project_id,
            requested_email=body.requested_email,
            requested_role=Role(body.requested_role),
            requested_by=requester,
            approver_email=approver,
            message=body.message,
            expires_at=expires_at,
        )
        version = self.store.current_version(body.project_id)
        event = EventEnvelope(
            stream_id=body.project_id,
            event_type="InvitationRequested",
            actor=requester,
            data={
                "invitation_id": invitation_id,
                "requested_email": requested_email,
                "requested_role": Role(body.requested_role).value,
                "approver_email": approver,
                "message": body.message,
            },
        )
        stored = self.store.append(body.project_id, version, [event])
        self.publisher.publish_events(body.project_id, stored)
        approval_url = f"{self.settings.public_url}/auth/invitations/approve?token={approval_token}"
        rejection_url = f"{self.settings.public_url}/auth/invitations/reject?token={approval_token}"
        self.mailer.send(
            approver,
            f"Approve access to project {snapshot.name}",
            (
                f"{requested_email} requested role {Role(body.requested_role).value} in project {snapshot.name}.\n\n"
                f"Message: {body.message or '(none)'}\n\n"
                f"Approve: {approval_url}\n"
                f"Reject: {rejection_url}\n\n"
                f"This request expires at {expires_at.isoformat()}."
            ),
        )
        return InvitationResult(invitation_id, "pending_approval", approver, requested_email)

    def approve(self, token: str) -> dict:
        row, access_token = self.store.approve_invitation(token)
        access_url = f"{self.settings.public_url}/auth/invitations/accept?token={access_token}"
        self.mailer.send(
            row["requested_email"],
            f"Access approved for project {row['project_id']}",
            (
                f"Your request for role {row['requested_role']} was approved.\n\n"
                f"Open this one-time link to create/access your account:\n{access_url}\n\n"
                f"The link expires at {row['expires_at'].isoformat()}."
            ),
        )
        version = self.store.current_version(row["project_id"])
        stored = self.store.append(
            row["project_id"],
            version,
            [
                EventEnvelope(
                    stream_id=row["project_id"],
                    event_type="InvitationApproved",
                    actor=row["approver_email"],
                    data={
                        "invitation_id": row["invitation_id"],
                        "requested_email": row["requested_email"],
                        "requested_role": row["requested_role"],
                    },
                )
            ],
        )
        self.publisher.publish_events(row["project_id"], stored)
        return row

    def reject(self, token: str) -> dict:
        return self.store.reject_invitation(token)

    def accept(self, token: str) -> dict:
        row = self.store.accept_invitation(token)
        self.store.ensure_user(row["requested_email"])
        current = self.store.current_version(row["project_id"])
        self.commands.execute(
            CommandEnvelope(
                command_type="membership.grant",
                project_id=row["project_id"],
                expected_version=current,
                actor=row["approver_email"],
                payload={"email": row["requested_email"], "role": row["requested_role"]},
            )
        )
        _, api_token = self.store.create_api_token(
            row["requested_email"], label=f"Invitation {row['invitation_id']}"
        )
        session = self.store.create_session(
            row["requested_email"],
            expires_at=datetime.now(UTC) + timedelta(hours=self.settings.session_ttl_hours),
        )
        return {
            "email": row["requested_email"],
            "project_id": row["project_id"],
            "role": row["requested_role"],
            "api_token": api_token,
            "session": session,
        }
