import datetime

import pytest

from metahound.diff import (
    diff_snapshots,
    snapshot_from_db_crawl,
    snapshot_from_file_crawl,
)
from metahound.cli_functions import changes_fn, _snapshot_and_diff


# ---------------------------------------------------------------------------
# diff_snapshots
# ---------------------------------------------------------------------------

def _table(columns):
    return {"kind": "table", "columns": columns}


def _file(columns):
    return {"kind": "file", "columns": columns}


class TestDiffSnapshots:
    def test_no_changes(self):
        snap = {"db://src/d/s/t": _table({"id": "integer", "name": "string"})}
        assert diff_snapshots(snap, snap) == []

    def test_table_added(self):
        old = {}
        new = {"db://src/d/s/t": _table({"id": "integer"})}
        changes = diff_snapshots(old, new)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "table_added"
        assert changes[0]["severity"] == "info"

    def test_table_removed_is_breaking(self):
        old = {"db://src/d/s/t": _table({"id": "integer"})}
        changes = diff_snapshots(old, {})
        assert len(changes) == 1
        assert changes[0]["change_type"] == "table_removed"
        assert changes[0]["severity"] == "breaking"

    def test_column_added(self):
        old = {"db://src/d/s/t": _table({"id": "integer"})}
        new = {"db://src/d/s/t": _table({"id": "integer", "email": "string"})}
        changes = diff_snapshots(old, new)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "column_added"
        assert changes[0]["severity"] == "info"
        assert changes[0]["detail"]["column"] == "email"

    def test_column_removed_is_breaking(self):
        old = {"db://src/d/s/t": _table({"id": "integer", "email": "string"})}
        new = {"db://src/d/s/t": _table({"id": "integer"})}
        changes = diff_snapshots(old, new)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "column_removed"
        assert changes[0]["severity"] == "breaking"

    def test_column_type_changed_is_breaking(self):
        old = {"db://src/d/s/t": _table({"id": "integer"})}
        new = {"db://src/d/s/t": _table({"id": "string"})}
        changes = diff_snapshots(old, new)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "column_type_changed"
        assert changes[0]["severity"] == "breaking"
        assert changes[0]["detail"] == {
            "column": "id", "old_type": "integer", "new_type": "string",
        }

    def test_file_added(self):
        old = {}
        new = {"sftp://src//a.csv": _file({"id": "integer"})}
        changes = diff_snapshots(old, new)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "file_added"
        assert changes[0]["severity"] == "info"

    def test_file_schema_changed_is_breaking(self):
        old = {"sftp://src//a.csv": _file({"id": "integer"})}
        new = {"sftp://src//a.csv": _file({"id": "string"})}
        changes = diff_snapshots(old, new)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "file_schema_changed"
        assert changes[0]["severity"] == "breaking"

    def test_file_without_schema_does_not_trigger_change(self):
        # get_schemas off yields empty columns; that is not a schema change
        old = {"sftp://src//a.csv": _file({"id": "integer"})}
        new = {"sftp://src//a.csv": _file({})}
        assert diff_snapshots(old, new) == []

    def test_file_removed_is_not_reported(self):
        old = {"sftp://src//a.csv": _file({"id": "integer"})}
        assert diff_snapshots(old, {}) == []


# ---------------------------------------------------------------------------
# snapshot builders
# ---------------------------------------------------------------------------

class TestSnapshotBuilders:
    def test_snapshot_from_db_crawl(self):
        db_json = {
            "database": "mydb",
            "schemas": {
                "myschema": [
                    {
                        "name": "users",
                        "properties": {
                            "id": {"type": ["integer"]},
                            "email": {"type": ["null", "string"]},
                        },
                    }
                ]
            },
        }
        snap = snapshot_from_db_crawl("mysource", db_json)
        assert snap == {
            "db://mysource/mydb/myschema/users": {
                "kind": "table",
                "columns": {"id": "integer", "email": "string"},
            }
        }

    def test_snapshot_from_file_crawl(self):
        file_list = [
            {"file": "a.csv", "properties": {"id": {"type": ["null", "integer", "string"]}}},
            {"file": "b.bin", "properties": {}},
        ]
        snap = snapshot_from_file_crawl("mysource", "sftp", file_list)
        assert snap["sftp://mysource//a.csv"] == {
            "kind": "file", "columns": {"id": "integer/string"},
        }
        assert snap["sftp://mysource//b.bin"] == {"kind": "file", "columns": {}}

    def test_snapshot_handles_datetime_anyof(self):
        file_list = [
            {"file": "a.csv", "properties": {"created_at": {"anyOf": [
                {"type": ["null", "string"], "format": "date-time"},
                {"type": ["null", "string"]},
            ]}}},
        ]
        snap = snapshot_from_file_crawl("mysource", "sftp", file_list)
        assert snap["sftp://mysource//a.csv"]["columns"] == {"created_at": "date-time"}


# ---------------------------------------------------------------------------
# Backend round-trip + changes_fn
# ---------------------------------------------------------------------------

class TestChangesWorkflow:
    def _run_two_scans(self, backend):
        old = {"db://src/d/s/t": _table({"id": "integer", "email": "string"})}
        new = {"db://src/d/s/t": _table({"id": "string"})}

        scan_1 = backend.register_scan(server="src", last_modified=datetime.datetime(2026, 1, 1))
        _snapshot_and_diff(backend, scan_1, "db://src", None, old)

        scan_2 = backend.register_scan(server="src", last_modified=datetime.datetime(2026, 1, 2))
        return _snapshot_and_diff(backend, scan_2, "db://src", backend.get_latest_snapshot("db://src"), new)

    def test_first_scan_is_silent_baseline(self, in_memory_backend):
        backend = in_memory_backend
        scan_id = backend.register_scan(server="src", last_modified=datetime.datetime(2026, 1, 1))
        changes = _snapshot_and_diff(
            backend, scan_id, "db://src", None,
            {"db://src/d/s/t": _table({"id": "integer"})},
        )
        assert changes == []
        assert backend.get_changes() == []
        assert backend.get_latest_snapshot("db://src") is not None

    def test_changes_recorded_and_retrieved(self, in_memory_backend):
        backend = in_memory_backend
        self._run_two_scans(backend)

        changes = backend.get_changes()
        types = {c["change_type"] for c in changes}
        assert types == {"column_type_changed", "column_removed"}
        assert all(c["severity"] == "breaking" for c in changes)

    def test_get_changes_default_only_latest_scan(self, in_memory_backend):
        backend = in_memory_backend
        self._run_two_scans(backend)

        # Third scan with no changes: default view should be empty again
        snapshot = backend.get_latest_snapshot("db://src")
        scan_3 = backend.register_scan(server="src", last_modified=datetime.datetime(2026, 1, 3))
        _snapshot_and_diff(backend, scan_3, "db://src", snapshot, snapshot)
        assert backend.get_changes() == []

        # But --since still sees the older changes
        since = datetime.datetime(2020, 1, 1)
        assert len(backend.get_changes(since=since)) == 2

    def test_changes_fn_output_and_exit_codes(self, in_memory_backend, capsys, monkeypatch):
        backend = in_memory_backend
        self._run_two_scans(backend)
        monkeypatch.setattr("metahound.cli_functions._get_backend", lambda: backend)

        changes_fn(since=None, fail_on=None)
        out = capsys.readouterr().out
        assert "column_type_changed" in out
        assert "breaking" in out

        with pytest.raises(SystemExit):
            changes_fn(since=None, fail_on="breaking")

    def test_changes_fn_no_changes(self, in_memory_backend, capsys, monkeypatch):
        monkeypatch.setattr("metahound.cli_functions._get_backend", lambda: in_memory_backend)
        changes_fn(since=None, fail_on="breaking")
        assert "No schema changes" in capsys.readouterr().out
