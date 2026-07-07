#!/usr/bin/env python3
"""sync_from_remote.py — Pull platform-config tables from remote PG into local SQLite.

This is a one-shot developer tool, not part of the runtime. It is safe to
re-run: it wipes the local config tables (providers / provider_keys /
channels / models / model_provider_routes / token_coefficients) and
re-fills them from a fresh pg_dump over SSH.

User data (users, api_keys, payments, billing_records, request_logs,
usage_logs, redemption_codes, pending_billing) is NEVER touched.

Usage:
  scripts/sync_from_remote.py                              # sync everything
  scripts/sync_from_remote.py --dry-run                    # only dump + parse
  scripts/sync_from_remote.py --tables providers,channels  # subset
  scripts/sync_from_remote.py --ssh-host user@host         # override SSH target
  scripts/sync_from_remote.py --ssh-key /path/key          # override SSH key
  scripts/sync_from_remote.py --remote-pg-host 10.0.0.1    # override PG host
  scripts/sync_from_remote.py --remote-pg-port 5433        # override PG port
  scripts/sync_from_remote.py --remote-pg-user foo         # override PG user
  scripts/sync_from_remote.py --remote-pg-password bar     # override PG password
  scripts/sync_from_remote.py --remote-pg-db mydb          # override PG db

Env vars (all optional):
  DEPLOY_REMOTE              ssh destination (default root@47.103.206.6)
  DEPLOY_SSH_KEY             ssh key (default ~/ai/aliyun-ai01.pem)
  REMOTE_PG_HOST             default 127.0.0.1
  REMOTE_PG_PORT             default 5432
  REMOTE_PG_USER             default high_api
  REMOTE_PG_PASSWORD         default high_api_dev
  REMOTE_PG_DB               default high_api
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Allow running this file directly (no __init__.py in scripts/) and from
# elsewhere via `python -m` style imports of sibling modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _sync_parser import parse_dump  # noqa: E402
from _sync_remap import IdRemap, SyncReport  # noqa: E402


# ── Defaults (mirrors bin/deploy.sh + remote backend/.env DATABASE_URL) ─
DEFAULT_SSH_HOST = "root@47.103.206.6"
DEFAULT_SSH_KEY = os.path.expanduser("~/ai/aliyun-ai01.pem")
DEFAULT_REMOTE_PG_HOST = "127.0.0.1"
DEFAULT_REMOTE_PG_PORT = "5432"
DEFAULT_REMOTE_PG_USER = "high_api"
DEFAULT_REMOTE_PG_PASSWORD = "high_api_dev"
DEFAULT_REMOTE_PG_DB = "high_api"
DEFAULT_TABLES = [
    "providers",
    "provider_keys",
    "channels",
    "models",
    "model_provider_routes",
    "token_coefficients",
]


def dump_remote_tables(
    *,
    ssh_host: str,
    ssh_key: str,
    pg_host: str,
    pg_port: str,
    pg_user: str,
    pg_password: str,
    pg_db: str,
    tables: list[str],
) -> str:
    """Run pg_dump on the remote over SSH and return the SQL text."""
    if not Path(ssh_key).exists():
        raise SystemExit(f"SSH key not found: {ssh_key} (set DEPLOY_SSH_KEY)")

    table_args = " ".join(f"-t {shlex.quote(t)}" for t in tables)
    remote_cmd = (
        f"PGPASSWORD={shlex.quote(pg_password)} "
        f"pg_dump -h {shlex.quote(pg_host)} -p {shlex.quote(pg_port)} "
        f"-U {shlex.quote(pg_user)} -d {shlex.quote(pg_db)} "
        f"--data-only --inserts --no-owner --no-privileges {table_args}"
    )
    ssh = ["ssh", "-i", ssh_key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           ssh_host, remote_cmd]

    print(f"[sync] dumping {len(tables)} tables from {ssh_host}:{pg_host}:{pg_port}/{pg_db} ...")
    proc = subprocess.run(ssh, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(
            f"remote pg_dump failed (rc={proc.returncode}):\n"
            f"  stdout: {proc.stdout[-500:]}\n"
            f"  stderr: {proc.stderr[-500:]}"
        )
    if not proc.stdout.strip():
        raise SystemExit(
            f"remote pg_dump returned empty output — is the remote PG reachable "
            f"at {pg_host}:{pg_port} as {pg_user}/{pg_db}?"
        )
    return proc.stdout


def write_dump_to_tempfile(sql: str) -> Path:
    """Write dump to a tempfile in /tmp and return its path."""
    fd, path = tempfile.mkstemp(prefix="claude-sync-dump-", suffix=".sql", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(sql)
    except Exception:
        os.unlink(path)
        raise
    return Path(path)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sync platform-config tables from remote PG into local SQLite.",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Dump + parse only; do not modify local DB.")
    p.add_argument("--tables", default=",".join(DEFAULT_TABLES),
                   help=f"Comma-separated tables (default: {','.join(DEFAULT_TABLES)})")
    p.add_argument("--ssh-host", default=os.environ.get("DEPLOY_REMOTE", DEFAULT_SSH_HOST))
    p.add_argument("--ssh-key", default=os.environ.get("DEPLOY_SSH_KEY", DEFAULT_SSH_KEY))
    p.add_argument("--remote-pg-host",
                   default=os.environ.get("REMOTE_PG_HOST", DEFAULT_REMOTE_PG_HOST))
    p.add_argument("--remote-pg-port",
                   default=os.environ.get("REMOTE_PG_PORT", DEFAULT_REMOTE_PG_PORT))
    p.add_argument("--remote-pg-user",
                   default=os.environ.get("REMOTE_PG_USER", DEFAULT_REMOTE_PG_USER))
    p.add_argument("--remote-pg-password",
                   default=os.environ.get("REMOTE_PG_PASSWORD", DEFAULT_REMOTE_PG_PASSWORD))
    p.add_argument("--remote-pg-db",
                   default=os.environ.get("REMOTE_PG_DB", DEFAULT_REMOTE_PG_DB))
    return p


# ── Async DB layer (Task 4 fills these in) ───────────────────────────

async def collect_local_max_ids() -> dict[str, int]:
    """Query local DB for MAX(id) per config table. Returns empty dict if table doesn't exist."""
    # Implementation in Task 4
    raise NotImplementedError


async def wipe_local_providers() -> None:
    """Delete all rows from local providers; FK cascade handles provider_keys + channels."""
    # Implementation in Task 4
    raise NotImplementedError


async def insert_local_rows(
    table: str, rows: list[list], remap: IdRemap, report: SyncReport
) -> None:
    """Insert parsed rows into local DB, applying id remap where needed."""
    # Implementation in Task 4
    raise NotImplementedError


async def reset_sqlite_sequences() -> None:
    """Reset sqlite_sequence for the 6 config tables to MAX(id)."""
    # Implementation in Task 4
    raise NotImplementedError


async def main_async(args: argparse.Namespace) -> int:
    report = SyncReport()
    report.start_time = time.time()

    tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    sql = dump_remote_tables(
        ssh_host=args.ssh_host,
        ssh_key=args.ssh_key,
        pg_host=args.remote_pg_host,
        pg_port=args.remote_pg_port,
        pg_user=args.remote_pg_user,
        pg_password=args.remote_pg_password,
        pg_db=args.remote_pg_db,
        tables=tables,
    )
    dump_path = write_dump_to_tempfile(sql)
    print(f"[sync] dump written to {dump_path} ({len(sql)} bytes)")

    try:
        parsed = parse_dump(sql)
        print(f"[sync] parsed: {', '.join(f'{t}={len(rows)}' for t, rows in parsed.items())}")

        if args.dry_run:
            print("[sync] --dry-run: skipping local DB write")
            return 0

        # Local DB work (Task 4)
        max_ids = await collect_local_max_ids()
        remap = IdRemap(
            start_provider_id=max_ids.get("providers", 0) + 1,
            start_model_id=max_ids.get("models", 0) + 1,
        )

        await wipe_local_providers()
        print("[sync] local providers wiped (FK cascade cleared provider_keys + channels)")

        # providers — must come first; sets up provider_ids remap
        if "providers" in parsed:
            await insert_local_rows("providers", parsed["providers"], remap, report)

        # models — second; sets up model_ids remap
        if "models" in parsed:
            await insert_local_rows("models", parsed["models"], remap, report)

        # dependent tables — order matters
        for t in ("provider_keys", "channels", "model_provider_routes", "token_coefficients"):
            if t in parsed:
                await insert_local_rows(t, parsed[t], remap, report)

        await reset_sqlite_sequences()
        print("[sync] sqlite_sequence reset")
    finally:
        os.unlink(dump_path)
        print(f"[sync] dump cleaned: {dump_path}")

    report.end_time = time.time()
    print()
    print(report.render())
    return report.exit_code()


def main() -> int:
    args = build_argparser().parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())