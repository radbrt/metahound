from metahound.fileset_inference import infer_filesets, normalize_filename
from metahound.filesets import evaluate_filesets, parse_filesets


def _file(name, columns=None):
    properties = None
    if columns:
        properties = {col: {"type": [t]} for col, t in columns.items()}
    return {"file": name, "properties": properties}


# ---------------------------------------------------------------------------
# Filename normalization
# ---------------------------------------------------------------------------

class TestNormalizeFilename:
    def test_dates(self):
        assert normalize_filename("orders_2026-07-09.csv") == "orders_{date}.csv"
        assert normalize_filename("orders_20260709.csv") == "orders_{date}.csv"
        assert normalize_filename("orders_2026_07_09.csv") == "orders_{date}.csv"

    def test_datetime_stamp(self):
        assert normalize_filename("export_20260709T121500.jsonl") == "export_{date}{time}.jsonl"
        assert normalize_filename("export_20260709121500.jsonl") == "export_{date}{time}.jsonl"

    def test_time(self):
        assert normalize_filename("snap_12:15:00.csv") == "snap_{time}.csv"

    def test_uuid(self):
        assert (
            normalize_filename("export_123e4567-e89b-12d3-a456-426614174000.jsonl")
            == "export_{uuid}.jsonl"
        )

    def test_sequence_numbers(self):
        assert normalize_filename("batch_42.parquet") == "batch_{seq}.parquet"
        assert normalize_filename("part-00001.csv") == "part-{seq}.csv"

    def test_path_is_stripped_to_basename(self):
        assert normalize_filename("incoming/orders_2026-07-09.csv") == "orders_{date}.csv"

    def test_no_volatile_parts(self):
        assert normalize_filename("readme.txt") == "readme.txt"


# ---------------------------------------------------------------------------
# Clustering and suggestion
# ---------------------------------------------------------------------------

class TestInferFilesets:
    def test_clusters_by_template(self):
        files = [
            _file("orders_2026-07-01.csv", {"id": "integer"}),
            _file("orders_2026-07-02.csv", {"id": "integer"}),
            _file("customers_2026-07-01.csv", {"email": "string"}),
            _file("customers_2026-07-02.csv", {"email": "string"}),
        ]
        events, leftover = infer_filesets(files, "sftp_source")

        assert leftover == []
        assert len(events) == 2
        by_name = {e["detail"]["name"]: e for e in events}
        assert by_name["customers"]["detail"]["pattern"] == "customers_{date}.csv"
        assert by_name["orders"]["detail"]["file_count"] == 2
        assert by_name["orders"]["object_uri"] == "fileset://sftp_source/orders"
        for event in events:
            assert event["change_type"] == "fileset_suggested"
            assert event["severity"] == "info"

    def test_suggestion_carries_columns_and_samples(self):
        files = [
            _file("orders_2026-07-01.csv", {"id": "integer", "total": "number"}),
            _file("orders_2026-07-02.csv", {"id": "integer", "total": "number"}),
        ]
        events, _ = infer_filesets(files, "src")
        detail = events[0]["detail"]
        assert detail["columns"] == {"id": "integer", "total": "number"}
        assert detail["sample_files"] == ["orders_2026-07-01.csv", "orders_2026-07-02.csv"]

    def test_single_file_is_not_suggested(self):
        files = [_file("orders_2026-07-01.csv", {"id": "integer"})]
        events, leftover = infer_filesets(files, "src")
        assert events == []
        assert leftover == files

    def test_static_filenames_never_cluster(self):
        # Identical templates that equal the literal filename are one file
        # seen twice across dirs — not a recurring feed.
        files = [_file("incoming/readme.txt"), _file("archive/readme.txt")]
        events, leftover = infer_filesets(files, "src")
        assert events == []
        assert leftover == files

    def test_schema_outlier_degrades_to_unrecognized(self):
        files = [
            _file("orders_2026-07-01.csv", {"id": "integer"}),
            _file("orders_2026-07-02.csv", {"id": "integer"}),
            _file("orders_2026-07-03.csv", {"totally": "string", "different": "string"}),
        ]
        events, leftover = infer_filesets(files, "src")
        assert len(events) == 1
        assert events[0]["detail"]["file_count"] == 2
        assert [f["file"] for f in leftover] == ["orders_2026-07-03.csv"]

    def test_schemaless_files_ride_along(self):
        files = [
            _file("orders_2026-07-01.csv", {"id": "integer"}),
            _file("orders_2026-07-02.csv"),
        ]
        events, leftover = infer_filesets(files, "src")
        assert len(events) == 1
        assert events[0]["detail"]["file_count"] == 2
        assert leftover == []

    def test_cluster_below_min_after_outliers_is_dropped(self):
        files = [
            _file("orders_2026-07-01.csv", {"id": "integer"}),
            _file("orders_2026-07-02.csv", {"other": "string"}),
        ]
        events, leftover = infer_filesets(files, "src")
        assert events == []
        assert len(leftover) == 2

    def test_name_collision_with_declared_fileset(self):
        files = [
            _file("orders_2026-07-01.csv", {"id": "integer"}),
            _file("orders_2026-07-02.csv", {"id": "integer"}),
        ]
        events, _ = infer_filesets(files, "src", declared_names={"orders"})
        assert events[0]["detail"]["name"] == "orders_2"


# ---------------------------------------------------------------------------
# Integration through evaluate_filesets
# ---------------------------------------------------------------------------

class TestEvaluateWithInference:
    def test_suggestions_replace_unrecognized_for_clustered_files(self):
        filesets = parse_filesets([{"name": "orders", "pattern": "orders_{date}.csv"}])
        files = [
            _file("orders_2026-07-01.csv", {"id": "integer"}),
            _file("invoices_2026-07-01.csv", {"amount": "number"}),
            _file("invoices_2026-07-02.csv", {"amount": "number"}),
            _file("mystery.bin"),
        ]
        _, events = evaluate_filesets(
            filesets, files, None, "src", "sftp", alert_unrecognized=True, infer=True,
        )

        types = [e["change_type"] for e in events]
        assert types.count("fileset_suggested") == 1
        assert types.count("unrecognized_file") == 1

        suggestion = next(e for e in events if e["change_type"] == "fileset_suggested")
        assert suggestion["detail"]["name"] == "invoices"
        unrecognized = next(e for e in events if e["change_type"] == "unrecognized_file")
        assert unrecognized["detail"]["file"] == "mystery.bin"

    def test_infer_disabled_keeps_all_unrecognized(self):
        filesets = parse_filesets([{"name": "orders", "pattern": "orders_{date}.csv"}])
        files = [
            _file("invoices_2026-07-01.csv", {"amount": "number"}),
            _file("invoices_2026-07-02.csv", {"amount": "number"}),
        ]
        _, events = evaluate_filesets(
            filesets, files, None, "src", "sftp", alert_unrecognized=True, infer=False,
        )
        assert [e["change_type"] for e in events] == ["unrecognized_file", "unrecognized_file"]

    def test_inference_works_with_no_declared_filesets(self):
        files = [
            _file("invoices_2026-07-01.csv", {"amount": "number"}),
            _file("invoices_2026-07-02.csv", {"amount": "number"}),
        ]
        entries, events = evaluate_filesets(
            [], files, None, "src", "sftp", alert_unrecognized=False, infer=True,
        )
        assert entries == {}
        assert [e["change_type"] for e in events] == ["fileset_suggested"]
