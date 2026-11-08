"""A sync's status write must keep both export blocks (reading-cards round table, A2)."""
import json

import status


def _setup(tmp_path, monkeypatch):
    path = tmp_path / "status" / "status.json"
    monkeypatch.setattr(status, "STATUS_FILE", path)
    status.write_export_block("kim", "to_read_export", {"status": "success", "count": 806})
    status.write_export_block("kim", "read_export", {"last_status": "success", "count": 7})
    return path


def test_status_write_preserves_both_export_blocks(tmp_path, monkeypatch):
    path = _setup(tmp_path, monkeypatch)
    status.write_status("kim", {"status": "success", "books_synced_this_run": 0})
    kim = json.loads(path.read_text())["kim"]
    assert kim["status"] == "success"
    assert kim["to_read_export"] == {"status": "success", "count": 806}
    assert kim["read_export"] == {"last_status": "success", "count": 7}


def test_failure_write_preserves_both_export_blocks(tmp_path, monkeypatch):
    path = _setup(tmp_path, monkeypatch)
    status.write_failure_status("kim", RuntimeError("boom"), 1.0)
    kim = json.loads(path.read_text())["kim"]
    assert kim["status"] == "failed"
    assert kim["to_read_export"]["count"] == 806
    assert kim["read_export"]["count"] == 7


def test_block_round_trip_and_legacy_wrappers(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert status.read_export_block("kim", "read_export") == {"last_status": "success", "count": 7}
    assert status.read_export_status("kim") == {"status": "success", "count": 806}
    assert status.read_export_block("justin", "read_export") == {}
