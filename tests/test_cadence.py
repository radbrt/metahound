import datetime
from unittest.mock import MagicMock, patch

from metahound.backend_handlers import GenericBackendHandler
from metahound.cadence import evaluate_cadence
from metahound.cli_functions import _scan_filesystem_source
from metahound.setup import Base


def _daily(day_count, start=datetime.datetime(2026, 7, 1, 6, 0)):
    return [start + datetime.timedelta(days=i) for i in range(day_count)]


# ---------------------------------------------------------------------------
# Interval statistics
# ---------------------------------------------------------------------------

class TestEvaluateCadence:
    def test_on_time_fileset_is_silent(self):
        arrivals = {"orders": _daily(5)}
        now = arrivals["orders"][-1] + datetime.timedelta(days=1)
        assert evaluate_cadence(arrivals, "src", now=now) == []

    def test_overdue_fileset_is_flagged_breaking(self):
        arrivals = {"orders": _daily(5)}
        now = arrivals["orders"][-1] + datetime.timedelta(days=3)
        events = evaluate_cadence(arrivals, "src", now=now)

        assert len(events) == 1
        event = events[0]
        assert event["change_type"] == "fileset_overdue"
        assert event["severity"] == "breaking"
        assert event["object_uri"] == "fileset://src/orders"
        assert event["detail"]["median_interval_seconds"] == 86400
        assert event["detail"]["overdue_seconds"] == 86400  # 3d late vs 2d allowance

    def test_boundary_exactly_at_allowance_is_silent(self):
        arrivals = {"orders": _daily(5)}
        now = arrivals["orders"][-1] + datetime.timedelta(days=2)
        assert evaluate_cadence(arrivals, "src", now=now) == []

    def test_custom_factor(self):
        arrivals = {"orders": _daily(5)}
        now = arrivals["orders"][-1] + datetime.timedelta(days=1, hours=13)
        assert evaluate_cadence(arrivals, "src", now=now) == []
        events = evaluate_cadence(arrivals, "src", now=now, overdue_factor=1.5)
        assert len(events) == 1

    def test_too_little_history_is_silent(self):
        arrivals = {"orders": _daily(2)}
        now = arrivals["orders"][-1] + datetime.timedelta(days=30)
        assert evaluate_cadence(arrivals, "src", now=now) == []

    def test_batch_arrivals_collapse_to_one_timestamp(self):
        # Three files landing in the same batch = one arrival, not history
        ts = datetime.datetime(2026, 7, 1)
        arrivals = {"orders": [ts, ts, ts]}
        now = ts + datetime.timedelta(days=30)
        assert evaluate_cadence(arrivals, "src", now=now) == []

    def test_median_is_robust_to_one_gap(self):
        # Daily feed with one weekend gap: median stays 1 day
        base = datetime.datetime(2026, 7, 1, 6, 0)
        offsets = [0, 1, 2, 4, 5, 6]  # day 3 missing
        arrivals = {"orders": [base + datetime.timedelta(days=o) for o in offsets]}
        now = base + datetime.timedelta(days=9)
        events = evaluate_cadence(arrivals, "src", now=now)
        assert len(events) == 1
        assert events[0]["detail"]["median_interval_seconds"] == 86400


# ---------------------------------------------------------------------------
# Backend arrival storage
# ---------------------------------------------------------------------------

class TestArrivalStorage:
    def _backend(self):
        backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
        Base.metadata.create_all(backend.connection)
        return backend

    def test_roundtrip_and_upsert(self):
        backend = self._backend()
        t1 = datetime.datetime(2026, 7, 1)
        t2 = datetime.datetime(2026, 7, 2)

        backend.record_file_arrivals("sftp://src/", [
            ("orders", "orders_1.csv", t1),
            ("orders", "orders_2.csv", t2),
            ("invoices", "inv_1.csv", t1),
        ])
        # Re-observing a file updates mtime instead of duplicating
        backend.record_file_arrivals("sftp://src/", [
            ("orders", "orders_2.csv", datetime.datetime(2026, 7, 3)),
        ])

        arrivals = backend.get_file_arrivals("sftp://src/")
        assert arrivals["invoices"] == [t1]
        assert arrivals["orders"] == [t1, datetime.datetime(2026, 7, 3)]

    def test_sources_are_isolated(self):
        backend = self._backend()
        backend.record_file_arrivals("sftp://a/", [("orders", "f.csv", datetime.datetime(2026, 7, 1))])
        assert backend.get_file_arrivals("sftp://b/") == {}


# ---------------------------------------------------------------------------
# End to end through _scan_filesystem_source
# ---------------------------------------------------------------------------

class TestScanWithCadence:
    def _scan(self, backend, file_names, mtime, **kwargs):
        filesystem = MagicMock()
        filesystem.get_files.return_value = [
            {"name": name, "mtime": mtime} for name in file_names
        ]
        filesystem.get_last_modified.return_value = mtime

        with patch(
            "metahound.cli_functions.handle_file",
            side_effect=lambda name, fs, get_schemas: {"file": name, "properties": {}},
        ):
            _scan_filesystem_source(
                "partner", "sftp", filesystem, backend, False,
                filesets_config=[{"name": "orders", "pattern": "orders_{date}.csv"}],
                infer_filesets=False,
                **kwargs,
            )

    def test_overdue_feed_produces_breaking_change(self):
        backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
        Base.metadata.create_all(backend.connection)

        base = datetime.datetime.utcnow() - datetime.timedelta(days=10)
        for day in range(4):
            self._scan(backend, [f"orders_2026-06-0{day + 1}.csv"], base + datetime.timedelta(days=day))

        # 10 days since base + 3 days of arrivals = last file ~7 days ago on a
        # daily cadence: well past the 2x allowance.
        self._scan(backend, [], datetime.datetime.utcnow())

        changes = backend.get_changes()
        overdue = [c for c in changes if c["change_type"] == "fileset_overdue"]
        assert len(overdue) == 1
        assert overdue[0]["severity"] == "breaking"
        assert overdue[0]["detail"]["fileset"] == "orders"

    def test_freshness_disabled_stays_silent(self):
        backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
        Base.metadata.create_all(backend.connection)

        base = datetime.datetime.utcnow() - datetime.timedelta(days=10)
        for day in range(4):
            self._scan(
                backend, [f"orders_2026-06-0{day + 1}.csv"],
                base + datetime.timedelta(days=day), freshness=False,
            )
        self._scan(backend, [], datetime.datetime.utcnow(), freshness=False)

        assert all(c["change_type"] != "fileset_overdue" for c in backend.get_changes())
