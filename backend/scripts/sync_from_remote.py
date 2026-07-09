"""Sync config tables from remote PostgreSQL into the local dev DB.

See ``docs/deploy.md`` §10 for the workflow this script implements.

What it does
------------
1. SSH into the production box and run ``pg_dump --data-only --column-inserts``
   against the live PostgreSQL, dumping only the six config tables.
2. Parse the dump, extracting every ``INSERT INTO ... VALUES ...`` statement
   (one per row, so we know which line to blame on failure).
3. Truncate / delete rows from the same six tables in the **local** DB in
   FK-safe order.
4. Replay the INSERTs, preserving the remote primary-key IDs so any
   existing rows that still reference those IDs (admin UI history,
   alembic_version row, etc.) keep working.
5. Advance PostgreSQL sequences past the highest inserted id so future
   INSERTs without explicit ids don't collide.

What it does NOT do
-------------------
* It does **not** touch business tables (``users`` / ``api_keys`` /
  ``payments`` / ``billing_records`` / ``request_logs`` /
  ``usage_records`` / ``redemption_codes`` / ``pending_billings``).
  Those keep local state.
* It does **not** copy schema. If the local DB is missing columns the
  remote has, run ``alembic upgrade head`` first (the docs tell you to).
* ``provider_keys.key_encrypted`` is moved as-is — AES-256-GCM ciphertext
  is opaque bytes. To *decrypt* locally, your ``UPSTREAM_KEY_ENCRYPTION_KEY``
  must match the remote one.

Run with::

    cd backend && uv run python -m scripts.sync_from_remote
    cd backend && uv run python -m scripts.sync_from_remote --dry-run
    cd backend && uv run python -m scripts.sync_from_remote \
        --tables providers,model_providers
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from typing import Iterable, Sequence

import aiosqlite
import asyncpg
import sqlalchemy as sa

from app.config import settings

logger = logging.getLogger("sync_from_remote")

# ---------------------------------------------------------------------------
# Defaults — overridable via env or CLI flags
# ---------------------------------------------------------------------------

DEFAULT_TABLES: tuple[str, ...] = (
    "providers",
    "provider_keys",
    "models",
    "model_providers",
    "channel_keys",
    "token_coefficient_configs",
)

# FK-safe deletion order: leaf tables first, roots last.  Mirrors the
# "delete children before parents" rule; works on both PostgreSQL and
# SQLite (which has no TRUNCATE / CASCADE).
DELETE_ORDER: tuple[str, ...] = (
    "token_coefficient_configs",
    "channel_keys",
    "model_providers",
    "provider_keys",
    "providers",
    "models",
)

# Insertion order is the reverse — parents first so child FKs resolve.
INSERT_ORDER: tuple[str, ...] = tuple(reversed(DELETE_ORDER))

DEFAULT_SSH_HOST = os.environ.get("DEPLOY_REMOTE", "root@47.103.206.6")
DEFAULT_SSH_KEY = os.environ.get(
    "DEPLOY_SSH_KEY", os.path.expanduser("~/ai/aliyun-ai01.pem")
)
DEFAULT_REMOTE_PG_HOST = os.environ.get("REMOTE_PG_HOST", "127.0.0.1")
DEFAULT_REMOTE_PG_PORT = int(os.environ.get("REMOTE_PG_PORT", "5432"))
DEFAULT_REMOTE_PG_USER = os.environ.get("REMOTE_PG_USER", "high_api")
DEFAULT_REMOTE_PG_PASSWORD = os.environ.get("REMOTE_PG_PASSWORD", "high_api_dev")
DEFAULT_REMOTE_PG_DB = os.environ.get("REMOTE_PG_DB", "high_api")


# ---------------------------------------------------------------------------
# Local-DB helpers
# ---------------------------------------------------------------------------


def _local_dialect(database_url: str) -> str:
    """Return 'postgresql' or 'sqlite' from the SQLAlchemy URL."""
    url = sa.make_url(database_url)
    return url.get_backend_name().split("+")[0]


def _sqlite_path(database_url: str) -> str:
    """Pull the file path out of a sqlite URL."""
    return sa.make_url(database_url).database or ":memory:"


def _pg_dsn(database_url: str) -> str:
    """Translate SQLAlchemy asyncpg URL → libpq DSN that asyncpg accepts."""
    u = sa.make_url(database_url)
    user = u.username or ""
    password = u.password or ""
    host = u.host or "localhost"
    port = u.port or 5432
    database = u.database or ""
    auth = f"{user}:{password}@" if user else ""
    return f"postgresql://{auth}{host}:{port}/{database}"


async def _clear_local_tables(database_url: str, tables: Sequence[str]) -> None:
    """Delete rows from each table in FK-safe order."""
    dialect = _local_dialect(database_url)

    if dialect == "postgresql":
        dsn = _pg_dsn(database_url)
        conn = await asyncpg.connect(dsn=dsn)
        try:
            table_list = ", ".join(f'"{t}"' for t in tables)
            # RESTART IDENTITY: reset SERIAL sequences to 1.
            # CASCADE: clears referencing rows if any sneak in.
            await conn.execute(f'TRUNCATE {table_list} RESTART IDENTITY CASCADE')
            logger.info("truncated local tables (PostgreSQL CASCADE)")
        finally:
            await conn.close()
        return

    # SQLite: ordered DELETEs (no TRUNCATE, no CASCADE).
    sqlite_path = _sqlite_path(database_url)
    async with aiosqlite.connect(sqlite_path) as db:
        await db.execute("PRAGMA foreign_keys = OFF")
        try:
            for table in DELETE_ORDER:
                if table not in tables:
                    continue
                await db.execute(f'DELETE FROM "{table}"')
            await db.commit()
            logger.info("deleted local rows (SQLite ordered)")
        finally:
            await db.execute("PRAGMA foreign_keys = ON")


async def _apply_inserts(database_url: str, dumps: dict[str, list[str]]) -> dict[str, int]:
    """Replay INSERTs in parent-first order, preserving remote PKs."""
    counts: dict[str, int] = {t: 0 for t in INSERT_ORDER}
    dialect = _local_dialect(database_url)

    if dialect == "postgresql":
        dsn = _pg_dsn(database_url)
        conn = await asyncpg.connect(dsn=dsn)
        try:
            for table in INSERT_ORDER:
                inserts = dumps.get(table, [])
                if not inserts:
                    continue
                # Single statement at a time — better error attribution.
                for stmt in inserts:
                    try:
                        await conn.execute(stmt)
                    except Exception as e:
                        logger.error("INSERT failed: %s", e)
                        logger.error("statement: %s", stmt[:200])
                        raise
                counts[table] = len(inserts)
        finally:
            await conn.close()
        return counts

    sqlite_path = _sqlite_path(database_url)
    async with aiosqlite.connect(sqlite_path) as db:
        await db.execute("PRAGMA foreign_keys = OFF")
        try:
            for table in INSERT_ORDER:
                inserts = dumps.get(table, [])
                if not inserts:
                    continue
                for stmt in inserts:
                    try:
                        await db.execute(stmt)
                    except Exception as e:
                        logger.error("INSERT failed: %s", e)
                        logger.error("statement: %s", stmt[:200])
                        raise
                counts[table] = len(inserts)
            await db.commit()
        finally:
            await db.execute("PRAGMA foreign_keys = ON")
    return counts


async def _advance_sequences(database_url: str) -> None:
    """After replaying INSERTs with explicit ids, bump sequences past MAX(id).

    Without this, the next auto-assigned id on PostgreSQL collides with
    the highest explicit one we just inserted (PG sequences don't observe
    explicit inserts).  SQLite handles this via the sqlite_sequence row.
    """
    if _local_dialect(database_url) != "postgresql":
        return
    dsn = _pg_dsn(database_url)
    conn = await asyncpg.connect(dsn=dsn)
    try:
        for table in INSERT_ORDER:
            await conn.execute(
                "SELECT setval(pg_get_serial_sequence($1, 'id'), "
                "COALESCE((SELECT MAX(id) FROM \""
                + table
                + "\"), 1))",
                table,
            )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Step 1 — pull the dump from the remote via SSH
# ---------------------------------------------------------------------------


def _build_pg_dump_remote_cmd(
    *,
    remote_pg_host: str,
    remote_pg_port: int,
    remote_pg_user: str,
    remote_pg_password: str,
    remote_pg_db: str,
    tables: Sequence[str],
) -> str:
    """Quote the pg_dump command so it survives a single SSH exec round-trip."""
    table_args = " ".join(f"-t {shlex.quote(t)}" for t in tables)
    # --column-inserts emits column names explicitly so the local INSERTs
    # only touch columns the local table has — schema drift on the
    # *remote* won't crash the import.
    return (
        "PGPASSWORD="
        + shlex.quote(remote_pg_password)
        + " pg_dump -h "
        + shlex.quote(remote_pg_host)
        + " -p "
        + shlex.quote(str(remote_pg_port))
        + " -U "
        + shlex.quote(remote_pg_user)
        + " -d "
        + shlex.quote(remote_pg_db)
        + " --data-only --no-owner --no-privileges --column-inserts "
        + table_args
    )


def fetch_remote_dump(
    *,
    ssh_host: str,
    ssh_key: str | None,
    remote_cmd: str,
    timeout: int = 300,
) -> str:
    """Run pg_dump on the remote over SSH and return the SQL text."""
    ssh_args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if ssh_key:
        ssh_args += ["-i", ssh_key]
    ssh_args += [ssh_host, "--", remote_cmd]

    logger.info("running ssh %s ... %s ...", ssh_host, remote_cmd.split(" ", 1)[0])

    try:
        proc = subprocess.run(
            ssh_args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise SystemExit(
            f"ssh/pg_dump timed out after {timeout}s — check connectivity to {ssh_host}"
        ) from e
    except FileNotFoundError as e:
        raise SystemExit("`ssh` not on PATH; install OpenSSH") from e

    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(
            f"ssh/pg_dump failed (exit {proc.returncode}); see stderr above"
        )
    if not proc.stdout:
        raise SystemExit("remote pg_dump returned no output")
    return proc.stdout


# ---------------------------------------------------------------------------
# Step 2 — parse INSERT statements out of the dump
# ---------------------------------------------------------------------------

_INSERT_HEAD = re.compile(
    r"""^INSERT\s+INTO\s+
        (?:\"?[A-Za-z_][\w]*\"?\.)?   # optional schema (e.g. public.)
        \"?(?P<table>[A-Za-z_][\w]*)\"?
        \s*\(""",
    re.VERBOSE | re.IGNORECASE,
)


def _strip_schema(table_ref: str) -> str:
    """`public.providers` -> `providers`."""
    if "." in table_ref:
        return table_ref.split(".", 1)[1].strip('"')
    return table_ref.strip('"')


def _split_statements(sql: str) -> list[tuple[str, str]]:
    """Yield (statement_text, statement_kind) where kind ∈ {insert, other}.

    Walks the dump linearly.  At each "interesting" boundary we look
    ahead for the next ``INSERT `` keyword *and* the next ``;`` — if
    the INSERT comes first, we recurse into the INSERT branch; if the
    ``;`` comes first (or there's no further INSERT), we skip to just
    past it and treat the gap as non-INSERT (SET / SELECT / etc).
    """
    out: list[tuple[str, str]] = []
    i = 0
    n = len(sql)
    insert_token = "INSERT "

    while i < n:
        while i < n and sql[i] in " \t\r\n":
            i += 1
        if i >= n:
            break

        # Is the current position an INSERT?
        if sql[i : i + len(insert_token)].upper() == insert_token:
            # Walk to the statement-terminating `;`, skipping over
            # strings, line comments, and paren groups (column list +
            # VALUES list + any nested calls).  Naive depth-only walking
            # would stop at the column list's closing `)` and lose the
            # VALUES clause.
            j = i
            paren_depth = 0
            saw_semi = False
            while j < n:
                c = sql[j]
                if c == "(":
                    paren_depth += 1
                    j += 1
                elif c == ")":
                    paren_depth -= 1
                    if paren_depth < 0:
                        raise SystemExit(
                            f"unbalanced parens in INSERT at offset {i}"
                        )
                    j += 1
                elif c == "'":
                    j += 1
                    while j < n:
                        if sql[j] == "'":
                            if j + 1 < n and sql[j + 1] == "'":
                                j += 2
                                continue
                            j += 1
                            break
                        j += 1
                elif c == "-" and sql[j + 1 : j + 3] == "--":
                    nl = sql.find("\n", j)
                    j = nl if nl >= 0 else n
                elif c == ";" and paren_depth == 0:
                    j += 1
                    saw_semi = True
                    break
                else:
                    j += 1
            if not saw_semi:
                raise SystemExit(f"INSERT at offset {i} has no terminating `;`")
            out.append((sql[i:j], "insert"))
            i = j
            continue

        # Non-INSERT territory.  We must NOT jump straight to the next
        # `;` — an INSERT might start in between (e.g. a SET block
        # followed by `--\n\nINSERT ...`).  Find both boundaries and
        # act on whichever comes first.
        next_semi = sql.find(";", i)
        next_insert = -1
        # Case-insensitive search for the next INSERT token
        search_from = i
        while True:
            k = sql.upper().find(insert_token, search_from)
            if k < 0:
                break
            # Require it be a word boundary (preceded by whitespace or
            # start-of-input) so we don't match e.g. `MYINSERT`.
            if k == 0 or sql[k - 1] in " \t\r\n":
                next_insert = k
                break
            search_from = k + 1

        if next_insert < 0 or (next_semi >= 0 and next_semi < next_insert):
            # No upcoming INSERT before the next ;  — skip non-INSERT stmt.
            if next_semi < 0:
                break
            i = next_semi + 1
        else:
            # An INSERT is coming up before the next ; — advance to it
            # and let the next loop iteration handle it.
            i = next_insert
    return out


def parse_dump(sql: str, allowed_tables: Iterable[str]) -> dict[str, list[str]]:
    """Return {table_name: [insert_sql, ...]} for tables we care about."""
    allowed = set(allowed_tables)
    tables: dict[str, list[str]] = {t: [] for t in allowed}

    for stmt, kind in _split_statements(sql):
        if kind != "insert":
            continue
        head = _INSERT_HEAD.match(stmt)
        if not head:
            logger.warning("could not parse INSERT head, skipping: %r", stmt[:80])
            continue
        table = _strip_schema(head.group("table"))
        if table not in allowed:
            logger.debug("skipping INSERT for non-allowed table %s", table)
            continue
        tables[table].append(stmt)

    return tables


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _scrub_url(url: str) -> str:
    """Hide the password when echoing a connection URL."""
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", url)


def _parse_table_list(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_TABLES)
    return [t.strip() for t in raw.split(",") if t.strip()]


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sync config tables from remote PG to local DB.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="dump + parse + report only; do not touch local DB",
    )
    p.add_argument(
        "--tables",
        type=str,
        default=None,
        help=(
            "comma-separated list of tables to sync "
            f"(default: {','.join(DEFAULT_TABLES)})"
        ),
    )
    p.add_argument(
        "--ssh-host", default=DEFAULT_SSH_HOST, help="SSH target (default: %(default)s)"
    )
    p.add_argument("--ssh-key", default=DEFAULT_SSH_KEY, help="SSH private key path")
    p.add_argument(
        "--remote-pg-host",
        default=DEFAULT_REMOTE_PG_HOST,
        help="remote PG host (default: 127.0.0.1 from the SSH box)",
    )
    p.add_argument("--remote-pg-port", type=int, default=DEFAULT_REMOTE_PG_PORT)
    p.add_argument("--remote-pg-user", default=DEFAULT_REMOTE_PG_USER)
    p.add_argument("--remote-pg-password", default=DEFAULT_REMOTE_PG_PASSWORD)
    p.add_argument("--remote-pg-db", default=DEFAULT_REMOTE_PG_DB)
    p.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="SSH+pg_dump timeout in seconds (default 300)",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable DEBUG logging",
    )
    return p


async def _run(args: argparse.Namespace) -> int:
    tables = _parse_table_list(args.tables)

    if args.ssh_key and not os.path.exists(args.ssh_key):
        logger.error("SSH key not found at %s", args.ssh_key)
        return 2

    remote_cmd = _build_pg_dump_remote_cmd(
        remote_pg_host=args.remote_pg_host,
        remote_pg_port=args.remote_pg_port,
        remote_pg_user=args.remote_pg_user,
        remote_pg_password=args.remote_pg_password,
        remote_pg_db=args.remote_pg_db,
        tables=tables,
    )

    t0 = time.monotonic()
    dump_sql = fetch_remote_dump(
        ssh_host=args.ssh_host,
        ssh_key=args.ssh_key,
        remote_cmd=remote_cmd,
        timeout=args.timeout,
    )
    dump_kb = len(dump_sql.encode("utf-8")) / 1024
    logger.info("fetched %.1f KiB of SQL in %.1fs", dump_kb, time.monotonic() - t0)

    dumps = parse_dump(dump_sql, allowed_tables=tables)
    counts_in = {t: len(dumps.get(t, [])) for t in tables}
    logger.info("parsed dump: %s", counts_in)

    if all(v == 0 for v in counts_in.values()):
        logger.warning(
            "no INSERTs parsed for the requested tables — aborting "
            "(double-check --tables and remote connectivity)"
        )
        return 1

    logger.info("local DB: %s", _scrub_url(settings.database_url))

    if args.dry_run:
        logger.info("--dry-run: not applying changes")
        return 0

    await _clear_local_tables(settings.database_url, tables)
    applied = await _apply_inserts(settings.database_url, dumps)
    await _advance_sequences(settings.database_url)

    elapsed = time.monotonic() - t0
    logger.info("done in %.1fs. rows applied: %s", elapsed, applied)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
