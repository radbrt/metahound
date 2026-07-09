import copy
from unittest.mock import MagicMock, patch

from metahound.backend_handlers import GenericBackendHandler
from metahound.cli_functions import _scan_openapi_source
from metahound.diff import diff_snapshots
from metahound.openapi import snapshot_from_openapi
from metahound.setup import Base

SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/orders": {
            "get": {
                "parameters": [
                    {"name": "since", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                ],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Order"},
                                }
                            }
                        }
                    }
                },
            },
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Order"}
                        }
                    }
                },
                "responses": {"201": {"description": "created"}},
            },
        },
    },
    "components": {
        "schemas": {
            "Order": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "total": {"type": "number"},
                    "lines": {"type": "array", "items": {"type": "object"}},
                },
            }
        }
    },
}


class TestSnapshotFromOpenAPI:
    def test_endpoints_and_schemas(self):
        snapshot = snapshot_from_openapi("partner_api", SPEC)

        get_endpoint = snapshot["api://partner_api/orders#get"]
        assert get_endpoint["kind"] == "endpoint"
        assert get_endpoint["columns"]["param.since"] == "string"
        assert get_endpoint["columns"]["param.limit"] == "integer"
        # response is an array of Order — its properties are flattened
        assert get_endpoint["columns"]["response.id"] == "integer"
        assert get_endpoint["columns"]["response.lines"] == "array[object]"

        post_endpoint = snapshot["api://partner_api/orders#post"]
        assert post_endpoint["columns"]["body.total"] == "number"

        order = snapshot["api://partner_api/components/schemas/Order"]
        assert order["kind"] == "schema"
        assert order["columns"] == {"id": "integer", "total": "number", "lines": "array[object]"}

    def test_unresolvable_ref_degrades(self):
        spec = {"paths": {"/x": {"get": {
            "responses": {"200": {"content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/Missing"}
            }}}},
        }}}}
        snapshot = snapshot_from_openapi("api", spec)
        assert snapshot["api://api/x#get"]["columns"] == {}


class TestSpecDrift:
    def test_drift_produces_breaking_changes(self):
        old = snapshot_from_openapi("partner_api", SPEC)

        new_spec = copy.deepcopy(SPEC)
        # response field type change + removed param + new endpoint
        new_spec["components"]["schemas"]["Order"]["properties"]["id"] = {"type": "string"}
        new_spec["paths"]["/orders"]["get"]["parameters"].pop(1)  # drop limit
        new_spec["paths"]["/customers"] = {"get": {"responses": {}}}
        new = snapshot_from_openapi("partner_api", new_spec)

        changes = diff_snapshots(old, new)
        by_key = {(c["change_type"], c["object_uri"], c["detail"].get("column")): c for c in changes}

        type_change = by_key[("column_type_changed", "api://partner_api/components/schemas/Order", "id")]
        assert type_change["severity"] == "breaking"
        assert by_key[("column_removed", "api://partner_api/orders#get", "param.limit")]["severity"] == "breaking"
        assert by_key[("endpoint_added", "api://partner_api/customers#get", None)]["severity"] == "info"
        # the GET response.id type change also surfaces on the endpoint
        assert ("column_type_changed", "api://partner_api/orders#get", "response.id") in by_key

    def test_endpoint_removal_is_breaking(self):
        old = snapshot_from_openapi("api", SPEC)
        new_spec = copy.deepcopy(SPEC)
        del new_spec["paths"]["/orders"]["post"]
        changes = diff_snapshots(old, snapshot_from_openapi("api", new_spec))

        removed = [c for c in changes if c["change_type"] == "endpoint_removed"]
        assert len(removed) == 1
        assert removed[0]["object_uri"] == "api://api/orders#post"
        assert removed[0]["severity"] == "breaking"


class TestScanOpenAPISource:
    def _scan(self, backend, spec):
        response = MagicMock()
        response.json.return_value = spec
        with patch("requests.get", return_value=response) as get:
            _scan_openapi_source(
                {"name": "partner_api", "type": "openapi",
                 "spec_url": "https://api.example.com/openapi.json",
                 "headers": {"Authorization": "Bearer t"}},
                backend,
            )
        return get

    def test_first_scan_baseline_then_drift(self):
        backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
        Base.metadata.create_all(backend.connection)

        get = self._scan(backend, SPEC)
        assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer t"}
        assert backend.get_changes() == []  # baseline

        new_spec = copy.deepcopy(SPEC)
        del new_spec["paths"]["/orders"]["post"]
        self._scan(backend, new_spec)

        changes = backend.get_changes()
        assert [c["change_type"] for c in changes] == ["endpoint_removed"]
        assert changes[0]["source_uri"] == "api://partner_api"

    def test_yaml_spec(self):
        from metahound.openapi import fetch_spec

        response = MagicMock()
        response.json.side_effect = ValueError("not json")
        response.text = "openapi: 3.0.0\npaths:\n  /ping:\n    get:\n      responses: {}\n"
        with patch("requests.get", return_value=response):
            spec = fetch_spec("https://api.example.com/openapi.yaml")
        assert "/ping" in spec["paths"]
