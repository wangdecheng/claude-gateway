"""Unit tests for IdRemap and SyncReport."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _sync_remap import IdRemap, SyncReport


def test_id_remap_assigns_sequential_local_ids():
    r = IdRemap(start_provider_id=10, start_model_id=20)
    assert r.next_provider_id(remote_id=100) == 10
    assert r.next_provider_id(remote_id=101) == 11
    assert r.next_provider_id(remote_id=102) == 12
    assert r.provider_ids == {100: 10, 101: 11, 102: 12}


def test_id_remap_lookup_returns_none_for_unknown():
    r = IdRemap(start_provider_id=1, start_model_id=1)
    assert r.provider_ids.get(999) is None


def test_id_remap_separate_provider_and_model_sequences():
    r = IdRemap(start_provider_id=1, start_model_id=1)
    pid = r.next_provider_id(remote_id=10)
    mid = r.next_model_id(remote_id=20)
    assert pid == 1
    assert mid == 1
    assert r.provider_ids[10] == 1
    assert r.model_ids[20] == 1


def test_report_render_summary():
    r = SyncReport()
    r.add("providers", inserted=8, skipped=0, failed=0)
    r.add("provider_keys", inserted=24, skipped=0, failed=0)
    r.add("channels", inserted=18, skipped=1, failed=0)
    out = r.render()
    assert "providers" in out
    assert "inserted=   8" in out
    assert "channels" in out
    assert "skipped=  1" in out
    assert "50 rows synced" in out


def test_report_exit_code_clean():
    r = SyncReport()
    r.add("providers", inserted=5, skipped=0, failed=0)
    assert r.exit_code() == 0


def test_report_exit_code_with_skipped():
    r = SyncReport()
    r.add("providers", inserted=5, skipped=1, failed=0)
    assert r.exit_code() == 1


def test_report_exit_code_with_failure():
    r = SyncReport()
    r.add("providers", inserted=5, skipped=0, failed=1)
    assert r.exit_code() == 2


if __name__ == "__main__":
    import sys
    import time

    _start = time.time()
    _passed = _failed = 0
    _test_funcs = [
        (name, obj) for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for _name, _fn in _test_funcs:
        try:
            _fn()
            _passed += 1
        except Exception as _e:
            _failed += 1
            print(f"FAIL {_name}: {_e}")
    _elapsed = time.time() - _start
    print(f"Ran {len(_test_funcs)} tests in {_elapsed:.2f}s — {'OK' if _failed == 0 else f'FAILED {_failed}'}")
    sys.exit(0 if _failed == 0 else 1)
