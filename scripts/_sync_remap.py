"""Id remap + sync report helpers for sync_from_remote.py.

These are pure logic, separated from the IO so they're trivial to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class IdRemap:
    """Tracks remote_id → local_id for tables whose PK is auto-incrementing.

    Local SQLite ids are assigned sequentially starting at `start_*_id`,
    which the caller should set to (local MAX(id) + 1) to avoid collisions.
    """

    def __init__(self, *, start_provider_id: int, start_model_id: int):
        self.provider_ids: dict[int, int] = {}
        self.model_ids: dict[int, int] = {}
        self._next_provider = start_provider_id
        self._next_model = start_model_id

    def next_provider_id(self, remote_id: int) -> int:
        local = self._next_provider
        self.provider_ids[remote_id] = local
        self._next_provider += 1
        return local

    def next_model_id(self, remote_id: int) -> int:
        local = self._next_model
        self.model_ids[remote_id] = local
        self._next_model += 1
        return local


@dataclass
class _TableStat:
    inserted: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass
class SyncReport:
    stats: dict[str, _TableStat] = field(default_factory=dict)
    skipped_details: list[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    def add(self, table: str, *, inserted: int, skipped: int, failed: int) -> None:
        s = self.stats.setdefault(table, _TableStat())
        s.inserted += inserted
        s.skipped += skipped
        s.failed += failed

    def note_skip(self, table: str, detail: str) -> None:
        self.skipped_details.append(f"{table}: {detail}")

    def render(self) -> str:
        lines = ["=== sync report ==="]
        total_inserted = total_skipped = total_failed = 0
        for table, s in self.stats.items():
            lines.append(
                f"{table:25s} inserted={s.inserted:>4}  "
                f"skipped={s.skipped:>3}  failed={s.failed:>3}"
            )
            total_inserted += s.inserted
            total_skipped += s.skipped
            total_failed += s.failed
        lines.append(
            f"total: {total_inserted} rows synced, {total_skipped} skipped, {total_failed} failed"
        )
        if self.skipped_details:
            lines.append("--- skipped details ---")
            for d in self.skipped_details[:20]:
                lines.append(f"  {d}")
            if len(self.skipped_details) > 20:
                lines.append(f"  ... and {len(self.skipped_details) - 20} more")
        if self.end_time and self.start_time:
            lines.append(f"elapsed: {self.end_time - self.start_time:.1f}s")
        return "\n".join(lines)

    def exit_code(self) -> int:
        total_failed = sum(s.failed for s in self.stats.values())
        total_skipped = sum(s.skipped for s in self.stats.values())
        if total_failed > 0:
            return 2
        if total_skipped > 0:
            return 1
        return 0
