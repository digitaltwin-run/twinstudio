from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from twinstudio.auth import AuthService
from twinstudio.bus import CommandBus, QueryService
from twinstudio.domain import InvitationRequest
from twinstudio.event_store import EventStore
from twinstudio.mqtt_bus import NullPublisher
from twinstudio.seed import seed_from_file
from twinstudio.settings import settings


def _latest_email(outbox: Path, recipient_fragment: str) -> str:
    candidates = sorted(path for path in outbox.glob("*.txt") if recipient_fragment in path.name)
    assert candidates
    return candidates[-1].read_text(encoding="utf-8")


def test_email_approval_creates_membership_and_token(tmp_path: Path) -> None:
    local = replace(
        settings,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
        smtp_host="",
        public_url="http://testserver",
        dev_auth_bypass=False,
    )
    local.ensure_directories()
    store = EventStore(local.database_url)
    publisher = NullPublisher()
    queries = QueryService(store)
    commands = CommandBus(store, publisher)
    source = Path(__file__).resolve().parents[1] / "examples" / "rpi5-camera3" / "project.json"
    seed_from_file(store, publisher, source)
    auth = AuthService(local, store, queries, commands, publisher)

    result = auth.request_access(
        InvitationRequest(
            project_id="demo-rpi5",
            requested_email="external@example.test",
            requested_role="editor",
            message="Please approve collaboration.",
        )
    )
    assert result.status == "pending_approval"

    outbox = local.data_dir / "outbox" / "emails"
    decision = _latest_email(outbox, "creator_at_example.test")
    approval_token = re.search(r"approve\?token=([^\s]+)", decision).group(1)
    auth.approve(approval_token)

    access = _latest_email(outbox, "external_at_example.test")
    access_token = re.search(r"accept\?token=([^\s]+)", access).group(1)
    accepted = auth.accept(access_token)
    assert accepted["email"] == "external@example.test"
    assert accepted["api_token"]
    snapshot = queries.project("demo-rpi5")
    assert snapshot.memberships["external@example.test"] == "editor"
    assert store.authenticate_api_token("external@example.test", accepted["api_token"])
