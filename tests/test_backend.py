def test_get_partition_parameterized(backend_with_data):
    """SQL injection prevention: URIs with single quotes must not raise and return empty df."""
    malicious_uri = "db://test_db/mydb/myschema/test_table/row_count' OR '1'='1"
    df = backend_with_data.get_partition(malicious_uri)
    assert len(df) == 0


def test_get_partition_returns_data(backend_with_data):
    """Normal URI returns the expected rows."""
    df = backend_with_data.get_partition("db://test_db/mydb/myschema/test_table/row_count")
    assert len(df) == 5
    assert list(df.columns) == ["ds", "y"]


def test_get_scan_payload_structure(backend_with_data):
    """get_scan_payload() returns a well-formed dict."""
    payload = backend_with_data.get_scan_payload()

    assert "sources" in payload
    assert "cli_version" in payload
    assert isinstance(payload["sources"], list)
    assert len(payload["sources"]) == 1

    source = payload["sources"][0]
    assert source["name"] == "test_db"
    assert source["uri"] == "db://test_db"
    assert "tables" in source
    assert len(source["tables"]) == 1

    table = source["tables"][0]
    assert table["name"] == "test_table"
    assert "metrics" in table
    assert len(table["metrics"]) == 5
    assert "fields" in table
    assert len(table["fields"]) == 1

    metric = table["metrics"][0]
    assert "metric_name" in metric
    assert "metric_value" in metric
    assert "ts" in metric
