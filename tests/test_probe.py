from unittest.mock import MagicMock, patch

import pytest

from metahound.backend_handlers import GenericBackendHandler
from metahound.cli_functions import _scan_openapi_source
from metahound.openapi import probe_endpoint, snapshot_from_probes
from metahound.setup import Base

ORDERS = [{"id": 1, "total": 9.5}, {"id": 2, "total": 12.0}]


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


class TestProbeEndpoint:
    def test_array_payload(self):
        with patch("requests.get", return_value=_response(ORDERS)):
            columns = probe_endpoint("https://api.example.com/orders")
        # generate_schema always allows string (JSONL heritage); what matters
        # for drift is that the inferred type is stable across scans
        assert columns == {"id": "integer/string", "total": "integer/string"}

    def test_object_payload(self):
        with patch("requests.get", return_value=_response({"status": "ok", "count": 3})):
            columns = probe_endpoint("https://api.example.com/health")
        assert set(columns) == {"status", "count"}

    def test_scalar_payload_yields_no_schema(self):
        with patch("requests.get", return_value=_response("pong")):
            assert probe_endpoint("https://api.example.com/ping") == {}


class TestSnapshotFromProbes:
    def test_entries_and_headers(self):
        probes = [{"name": "orders", "url": "https://api.example.com/orders",
                   "headers": {"X-Extra": "1"}}]
        with patch("requests.get", return_value=_response(ORDERS)) as get:
            entries = snapshot_from_probes("partner", probes, {"Authorization": "Bearer t"}, None)

        assert entries["api://partner/probe/orders"]["kind"] == "probe"
        assert entries["api://partner/probe/orders"]["columns"]["id"] == "integer/string"
        # shared headers merged with per-probe headers
        assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer t", "X-Extra": "1"}

    def test_failed_probe_carries_previous_entry(self):
        previous = {"api://partner/probe/orders": {"kind": "probe", "columns": {"id": "integer"}}}
        with patch("requests.get", side_effect=ConnectionError("down")):
            entries = snapshot_from_probes(
                "partner", [{"name": "orders", "url": "https://x"}], None, previous,
            )
        assert entries == previous

    def test_failed_probe_without_history_is_absent(self):
        with patch("requests.get", side_effect=ConnectionError("down")):
            entries = snapshot_from_probes(
                "partner", [{"name": "orders", "url": "https://x"}], None, None,
            )
        assert entries == {}

    def test_probe_requires_name_and_url(self):
        with pytest.raises(ValueError):
            snapshot_from_probes("partner", [{"name": "x"}], None, None)


class TestScanWithProbes:
    def _scan(self, backend, payload):
        with patch("requests.get", return_value=_response(payload)):
            _scan_openapi_source(
                {"name": "partner", "type": "openapi",
                 "probe": [{"name": "orders", "url": "https://api.example.com/orders"}]},
                backend,
            )

    def test_probe_drift_is_breaking(self):
        backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
        Base.metadata.create_all(backend.connection)

        self._scan(backend, ORDERS)
        assert backend.get_changes() == []  # baseline

        # upstream changed id to a string and dropped total
        self._scan(backend, [{"id": "a1"}, {"id": "a2"}])

        by_type = {c["change_type"]: c for c in backend.get_changes()}
        assert by_type["column_type_changed"]["severity"] == "breaking"
        assert by_type["column_type_changed"]["detail"]["column"] == "id"
        assert by_type["column_removed"]["detail"]["column"] == "total"
        assert by_type["column_removed"]["object_uri"] == "api://partner/probe/orders"

    def test_source_requires_spec_or_probe(self):
        backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
        Base.metadata.create_all(backend.connection)
        with pytest.raises(ValueError):
            _scan_openapi_source({"name": "empty", "type": "openapi"}, backend)
