from __future__ import annotations

import argparse
from pathlib import Path

from twinstudio.artifacts import export_project_bundle
from twinstudio.bus import QueryService
from twinstudio.event_store import EventStore
from twinstudio.settings import settings

parser = argparse.ArgumentParser()
parser.add_argument("--project", required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
queries = QueryService(EventStore(settings.database_url))
snapshot = queries.project(args.project)
export_project_bundle(snapshot, queries.events(args.project), args.out, project_root=Path.cwd())
print(args.out)
