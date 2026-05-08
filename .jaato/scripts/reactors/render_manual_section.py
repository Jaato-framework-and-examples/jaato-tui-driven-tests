"""Reactor — record an audit sidecar for the manual_writer's outcome.

The .md content lives in the file the agent wrote/updated directly via
``writeNewFile`` / ``updateFile``; this reactor's only job is to keep an
auditable record of what was done.  Writes
``manual/.payloads/<feature_id>.json`` with the lightweight completion
payload (decision, output_path, summary, warnings, errors, timestamp).

Used for:

- Run-over-run drift checking (compare two sidecars to see what the
  agent decided per run).
- Failure auditing (warnings / errors fields surface here).
- Future telemetry hooks (downstream consumers can subscribe to the
  reactor's effect rather than parsing the .md tree).

Not strictly required for the cascade to work — the .md alone is the
manual.  But cheap to keep and useful when something goes wrong.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def execute(params: Dict[str, Any], event: Dict[str, Any], context: Any) -> None:
    payload = event.get("payload") or {}
    fid = payload.get("feature_id")
    if not fid:
        context.logger.error(
            "manual_writer reactor: payload missing feature_id; skipping audit sidecar"
        )
        return

    workspace = Path(context.workspace_path)
    payloads_dir = workspace / "manual" / ".payloads"
    payloads_dir.mkdir(parents=True, exist_ok=True)

    sidecar = payloads_dir / f"{fid}.json"
    record = dict(payload)
    record["audit_timestamp"] = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    sidecar.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    context.logger.info(
        f"manual_writer reactor: audit sidecar written → {sidecar.name} "
        f"(decision={payload.get('decision')})"
    )
