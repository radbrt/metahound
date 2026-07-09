import datetime
import io
import json
from unittest.mock import MagicMock, patch

from metahound.backend_handlers import GenericBackendHandler
from metahound.cli_functions import _scan_filesystem_source
from metahound.file_handlers.jsonl_handler import JSONLHandler
from metahound.file_handlers.parquet_handler import ParquetHandler
from metahound.setup import Base


def _backend():
    backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
    Base.metadata.create_all(backend.connection)
    return backend


# ---------------------------------------------------------------------------
# Backend storage
# ---------------------------------------------------------------------------

class TestMergeFilesetMetrics:
    def test_roundtrip_through_outlier_partitions(self):
        backend = _backend()
        ts = datetime.datetime(2026, 7, 1)
        backend.merge_fileset_metrics("partner", [
            ("orders", "file_size", 1024, ts),
            ("orders", "file_size", 2048, ts + datetime.timedelta(days=1)),
            ("orders", "column_count", 5, ts),
        ])

        partitions = backend.get_partitions()
        assert "fileset://partner/orders/file_size" in partitions
        assert "fileset://partner/orders/column_count" in partitions

        df = backend.get_partition("fileset://partner/orders/file_size")
        assert list(df["y"]) == [1024.0, 2048.0]

    def test_duplicate_points_and_none_values_are_skipped(self):
        backend = _backend()
        ts = datetime.datetime(2026, 7, 1)
        backend.merge_fileset_metrics("partner", [("orders", "file_size", 1024, ts)])
        backend.merge_fileset_metrics("partner", [
            ("orders", "file_size", 9999, ts),        # same uri+ts: skipped
            ("orders", "row_count", None, ts),        # None: skipped
        ])

        df = backend.get_partition("fileset://partner/orders/file_size")
        assert list(df["y"]) == [1024.0]
        assert "fileset://partner/orders/row_count" not in backend.get_partitions()


# ---------------------------------------------------------------------------
# End to end through the scan
# ---------------------------------------------------------------------------

class TestScanRecordsFileMetrics:
    def _scan(self, backend, files, **kwargs):
        # files: {name: (size, mtime, schema_dict)}
        filesystem = MagicMock()
        # Regression: SFTP's get_files is a generator — the scan must survive
        # iterating the listing more than once.
        filesystem.get_files.return_value = (
            {"name": name, "size": size, "mtime": mtime}
            for name, (size, mtime, _) in files.items()
        )
        filesystem.get_last_modified.return_value = max(m for _, m, _ in files.values())

        def fake_handle(file_name, fs, get_schemas):
            schema = files[file_name][2]
            return {
                "file": file_name,
                "properties": {c: {"type": [t]} for c, t in schema.items()},
            }

        with patch("metahound.cli_functions.handle_file", side_effect=fake_handle):
            _scan_filesystem_source(
                "partner", "sftp", filesystem, backend, True,
                filesets_config=[{"name": "orders", "pattern": "orders_{date}.csv"}],
                infer_filesets=False,
                **kwargs,
            )

    def test_metrics_recorded_per_member(self):
        backend = _backend()
        t1 = datetime.datetime(2026, 7, 1)
        t2 = datetime.datetime(2026, 7, 2)
        self._scan(backend, {
            "orders_2026-07-01.csv": (1000, t1, {"id": "integer"}),
            "orders_2026-07-02.csv": (2000, t2, {"id": "integer"}),
            "mystery.bin": (5, t1, {}),
        })

        size_series = backend.get_partition("fileset://partner/orders/file_size")
        assert list(size_series["y"]) == [1000.0, 2000.0]
        cols_series = backend.get_partition("fileset://partner/orders/column_count")
        assert list(cols_series["y"]) == [1.0, 1.0]
        # unmatched files contribute nothing
        assert not any("mystery" in p for p in backend.get_partitions())

    def test_arrivals_survive_generator_listing(self):
        # The v2.6.0 freshness pass silently recorded nothing when get_files
        # yielded a generator (SFTP). The listing is materialized now.
        backend = _backend()
        t1 = datetime.datetime(2026, 7, 1)
        self._scan(backend, {"orders_2026-07-01.csv": (1000, t1, {"id": "integer"})})
        arrivals = backend.get_file_arrivals("sftp://partner/")
        assert arrivals == {"orders": [t1]}

    def test_file_metrics_disabled(self):
        backend = _backend()
        t1 = datetime.datetime(2026, 7, 1)
        self._scan(
            backend,
            {"orders_2026-07-01.csv": (1000, t1, {"id": "integer"})},
            file_metrics=False,
        )
        assert backend.get_partitions() == []


# ---------------------------------------------------------------------------
# Handler-level metrics
# ---------------------------------------------------------------------------

class TestParquetRowCount:
    def test_num_rows_from_metadata(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.table({"id": list(range(42)), "name": ["x"] * 42})
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        buffer.seek(0)

        meta = ParquetHandler(buffer, "batch.parquet", get_schema=True).get_file_metadata()
        assert meta["num_rows"] == 42
        assert set(meta["properties"]) == {"id", "name"}


class TestJSONLSampling:
    def test_samples_beyond_byte_hint(self):
        # 500 rows ≈ 20 KB; the old readlines(max_records) byte-hint bug
        # sampled only the first ~1000 bytes.
        rows = [json.dumps({"id": i, "payload": "x" * 30}) for i in range(500)]
        stream = io.BytesIO(("\n".join(rows) + "\n").encode())

        handler = JSONLHandler(stream, "events.jsonl", get_schema=True)
        _, samples = handler.sample_file(sample_rate=100, max_records=1000)
        # Every 100th of 500 rows → 5 samples; the byte-hint bug yielded 1
        assert len(samples) == 5
