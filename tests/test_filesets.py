import datetime
from unittest.mock import MagicMock, patch

import pytest

from metahound.backend_handlers import GenericBackendHandler
from metahound.cli_functions import _scan_filesystem_source
from metahound.diff import diff_snapshots
from metahound.filesets import (
    Fileset,
    evaluate_filesets,
    fileset_uri,
    parse_filesets,
)
from metahound.setup import Base


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

class TestFilesetMatching:
    def test_glob_matches_basename(self):
        fs = Fileset("orders", pattern="orders_*.csv")
        assert fs.matches("orders_2024.csv")
        assert fs.matches("upload/incoming/orders_2024.csv")
        assert not fs.matches("customers_2024.csv")

    def test_glob_with_path_matches_full_path(self):
        fs = Fileset("orders", pattern="incoming/orders_*.csv")
        assert fs.matches("incoming/orders_2024.csv")
        assert not fs.matches("archive/orders_2024.csv")

    def test_date_token(self):
        fs = Fileset("orders", pattern="orders_{date}.csv")
        assert fs.matches("orders_2024-06-01.csv")
        assert fs.matches("orders_20240601.csv")
        assert not fs.matches("orders_junk.csv")
        assert not fs.matches("orders_2024-06-01.csv.bak")

    def test_seq_and_uuid_tokens(self):
        assert Fileset("f", pattern="batch_{seq}.parquet").matches("batch_42.parquet")
        assert not Fileset("f", pattern="batch_{seq}.parquet").matches("batch_.parquet")
        uuid_fs = Fileset("f", pattern="export_{uuid}.jsonl")
        assert uuid_fs.matches("export_123e4567-e89b-12d3-a456-426614174000.jsonl")
        assert not uuid_fs.matches("export_not-a-uuid.jsonl")

    def test_regex(self):
        fs = Fileset("orders", regex=r"orders_\d{8}\.csv")
        assert fs.matches("orders_20240601.csv")
        assert not fs.matches("orders_2024.csv")


class TestParseFilesets:
    def test_parses_list(self):
        filesets = parse_filesets([
            {"name": "orders", "pattern": "orders_*.csv"},
            {"name": "customers", "regex": r"customers_\d+\.csv"},
        ])
        assert [f.name for f in filesets] == ["orders", "customers"]

    def test_none_gives_empty(self):
        assert parse_filesets(None) == []

    def test_requires_name(self):
        with pytest.raises(ValueError):
            parse_filesets([{"pattern": "*.csv"}])

    def test_requires_exactly_one_of_pattern_regex(self):
        with pytest.raises(ValueError):
            parse_filesets([{"name": "x"}])
        with pytest.raises(ValueError):
            parse_filesets([{"name": "x", "pattern": "*.csv", "regex": ".*"}])

    def test_duplicate_names_rejected(self):
        with pytest.raises(ValueError):
            parse_filesets([
                {"name": "x", "pattern": "a*"},
                {"name": "x", "pattern": "b*"},
            ])

    def test_unknown_keys_rejected(self):
        with pytest.raises(ValueError):
            parse_filesets([{"name": "x", "pattern": "a*", "regx": "typo"}])


# ---------------------------------------------------------------------------
# evaluate_filesets
# ---------------------------------------------------------------------------

def _csv_file(name, columns):
    return {"file": name, "properties": {c: {"type": [t]} for c, t in columns.items()}}


class TestEvaluateFilesets:
    def _filesets(self):
        return parse_filesets([{"name": "orders", "pattern": "orders_*.csv"}])

    def test_first_file_sets_canonical_silently(self):
        entries, events = evaluate_filesets(
            self._filesets(),
            [_csv_file("orders_1.csv", {"id": "integer", "amount": "number"})],
            previous=None, source_name="src", protocol="sftp",
        )
        assert events == []
        canonical = entries[fileset_uri("src", "orders")]["columns"]
        assert set(canonical) == {"id", "amount"}

    def test_mismatch_is_breaking_with_fileset_detail(self):
        files = [
            _csv_file("orders_1.csv", {"id": "integer", "amount": "number"}),
            _csv_file("orders_2.csv", {"id": "integer", "amount": "string"}),
        ]
        entries, events = evaluate_filesets(
            self._filesets(), files, previous=None, source_name="src", protocol="sftp",
        )
        assert len(events) == 1
        event = events[0]
        assert event["change_type"] == "file_schema_changed"
        assert event["severity"] == "breaking"
        assert event["detail"]["fileset"] == "orders"
        assert "orders_2.csv" in event["object_uri"]
        # canonical stays at the baseline, not the deviating file
        assert entries[fileset_uri("src", "orders")]["columns"]["amount"] == "number"

    def test_canonical_carried_from_previous_snapshot(self):
        previous = {
            fileset_uri("src", "orders"): {
                "kind": "fileset",
                "columns": {"id": "integer", "amount": "number"},
            }
        }
        _, events = evaluate_filesets(
            self._filesets(),
            [_csv_file("orders_9.csv", {"id": "integer", "amount": "string"})],
            previous=previous, source_name="src", protocol="sftp",
        )
        assert len(events) == 1
        assert events[0]["change_type"] == "file_schema_changed"

    def test_unrecognized_file_is_info(self):
        _, events = evaluate_filesets(
            self._filesets(),
            [_csv_file("mystery.csv", {"a": "string"})],
            previous=None, source_name="src", protocol="sftp",
        )
        assert len(events) == 1
        assert events[0]["change_type"] == "unrecognized_file"
        assert events[0]["severity"] == "info"
        assert events[0]["detail"]["declared_filesets"] == ["orders"]

    def test_alert_unrecognized_off(self):
        _, events = evaluate_filesets(
            self._filesets(),
            [_csv_file("mystery.csv", {"a": "string"})],
            previous=None, source_name="src", protocol="sftp",
            alert_unrecognized=False,
        )
        assert events == []

    def test_schemaless_file_recognized_but_not_validated(self):
        # get_schemas off: file matches, counts as recognized, no validation
        _, events = evaluate_filesets(
            self._filesets(),
            [{"file": "orders_1.csv", "properties": {}}],
            previous=None, source_name="src", protocol="sftp",
        )
        assert events == []

    def test_first_matching_fileset_wins(self):
        filesets = parse_filesets([
            {"name": "orders_daily", "pattern": "orders_{date}.csv"},
            {"name": "orders_any", "pattern": "orders_*.csv"},
        ])
        entries, events = evaluate_filesets(
            filesets,
            [_csv_file("orders_2024-06-01.csv", {"id": "integer"})],
            previous=None, source_name="src", protocol="sftp",
        )
        assert entries[fileset_uri("src", "orders_daily")]["columns"] == {"id": "integer"}
        assert entries[fileset_uri("src", "orders_any")]["columns"] == {}


# ---------------------------------------------------------------------------
# Fileset entries through the diff engine
# ---------------------------------------------------------------------------

class TestFilesetDiff:
    def test_fileset_added_is_info(self):
        new = {fileset_uri("src", "orders"): {"kind": "fileset", "columns": {"id": "integer"}}}
        changes = diff_snapshots({}, new)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "fileset_added"
        assert changes[0]["severity"] == "info"

    def test_fileset_removed_is_info(self):
        old = {fileset_uri("src", "orders"): {"kind": "fileset", "columns": {"id": "integer"}}}
        changes = diff_snapshots(old, {})
        assert len(changes) == 1
        assert changes[0]["change_type"] == "fileset_removed"
        assert changes[0]["severity"] == "info"

    def test_fileset_schema_changed_is_breaking(self):
        uri = fileset_uri("src", "orders")
        old = {uri: {"kind": "fileset", "columns": {"id": "integer"}}}
        new = {uri: {"kind": "fileset", "columns": {"id": "string"}}}
        changes = diff_snapshots(old, new)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "fileset_schema_changed"
        assert changes[0]["severity"] == "breaking"


# ---------------------------------------------------------------------------
# End to end through _scan_filesystem_source
# ---------------------------------------------------------------------------

class TestScanWithFilesets:
    def _make_backend(self):
        backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
        Base.metadata.create_all(backend.connection)
        return backend

    def _scan(self, backend, files_by_name, mtime):
        filesystem = MagicMock()
        filesystem.get_files.return_value = [
            {"name": name, "mtime": mtime} for name in files_by_name
        ]
        filesystem.get_last_modified.return_value = mtime

        def fake_handle(file_name, fs, get_schemas):
            return _csv_file(file_name, files_by_name[file_name])

        with patch("metahound.cli_functions.handle_file", side_effect=fake_handle):
            _scan_filesystem_source(
                "partner", "sftp", filesystem, backend, True,
                filesets_config=[{"name": "orders", "pattern": "orders_*.csv"}],
            )

    def test_mismatch_and_unrecognized_recorded_across_scans(self):
        backend = self._make_backend()

        # First scan: baseline, no events
        self._scan(backend, {"orders_1.csv": {"id": "integer"}}, datetime.datetime(2024, 1, 1))
        assert backend.get_changes() == []

        # Second scan: one deviating file, one unrecognized file
        self._scan(
            backend,
            {"orders_2.csv": {"id": "string"}, "mystery.bin": {}},
            datetime.datetime(2024, 2, 1),
        )
        changes = backend.get_changes()
        by_type = {c["change_type"]: c for c in changes}
        assert by_type["file_schema_changed"]["severity"] == "breaking"
        assert by_type["file_schema_changed"]["detail"]["fileset"] == "orders"
        assert by_type["unrecognized_file"]["severity"] == "info"
        # the deviating file itself still shows up as a new file
        assert "file_added" in by_type

    def test_fileset_removed_when_dropped_from_config(self):
        backend = self._make_backend()
        self._scan(backend, {"orders_1.csv": {"id": "integer"}}, datetime.datetime(2024, 1, 1))

        filesystem = MagicMock()
        filesystem.get_files.return_value = []
        filesystem.get_last_modified.return_value = datetime.datetime(2024, 2, 1)
        _scan_filesystem_source("partner", "sftp", filesystem, backend, True, filesets_config=None)

        changes = backend.get_changes()
        assert [c["change_type"] for c in changes] == ["fileset_removed"]
