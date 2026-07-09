"""
OpenAPI spec drift detection.

An `openapi` source fetches a spec URL on every scan and snapshots it in the
same {uri: {kind, columns}} shape the diff engine already understands, so
API drift flows through the standard change stream:

- Each path+method becomes an object of kind "endpoint" whose "columns" are
  the request parameters (param.{name}), request-body properties
  (body.{name}) and first-2xx response properties (response.{name})
- Each component schema becomes an object of kind "schema" whose columns are
  its properties

Removals and type changes are breaking (a consumer's pipeline is about to
break); additions are info. $refs are resolved against components with a
cycle guard; anything unresolvable degrades to type "object".
"""
import logging

logger = logging.getLogger(__name__)

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
MAX_REF_DEPTH = 10


def fetch_spec(spec_url: str, headers: dict | None = None) -> dict:
    """Fetch and parse an OpenAPI spec (JSON or YAML)."""
    import requests
    from yaml import safe_load

    response = requests.get(spec_url, headers=headers or {}, timeout=30)
    response.raise_for_status()

    try:
        return response.json()
    except ValueError:
        return safe_load(response.text)


def _resolve_ref(node: dict, spec: dict, depth: int = 0) -> dict:
    """Follow $ref pointers of the form #/components/schemas/Name."""
    while isinstance(node, dict) and "$ref" in node and depth < MAX_REF_DEPTH:
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return {}
        target = spec
        for part in ref[2:].split("/"):
            if not isinstance(target, dict) or part not in target:
                return {}
            target = target[part]
        node = target
        depth += 1
    return node if isinstance(node, dict) else {}


def _schema_type(schema: dict, spec: dict) -> str:
    schema = _resolve_ref(schema, spec)
    schema_type = schema.get("type", "object")
    if schema_type == "array":
        items = _resolve_ref(schema.get("items", {}), spec)
        return f"array[{items.get('type', 'object')}]"
    return schema_type


def _schema_properties(schema: dict, spec: dict, prefix: str = "") -> dict:
    """Flatten a schema's top-level properties into {name: type}."""
    schema = _resolve_ref(schema, spec)
    if schema.get("type") == "array":
        schema = _resolve_ref(schema.get("items", {}), spec)

    columns = {}
    for name, prop in (schema.get("properties") or {}).items():
        columns[f"{prefix}{name}"] = _schema_type(prop, spec)
    return columns


def _first_2xx_response(operation: dict) -> dict:
    for status, response in sorted((operation.get("responses") or {}).items()):
        if str(status).startswith("2"):
            return response
    return {}


def _json_content_schema(node: dict, spec: dict) -> dict:
    node = _resolve_ref(node, spec)
    content = node.get("content") or {}
    for content_type, media in content.items():
        if "json" in content_type:
            return media.get("schema") or {}
    return {}


def snapshot_from_openapi(source_name: str, spec: dict) -> dict:
    """Build a diff-engine snapshot from a parsed OpenAPI spec."""
    snapshot = {}

    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        shared_params = path_item.get("parameters") or []

        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue

            columns = {}
            for param in list(shared_params) + list(operation.get("parameters") or []):
                param = _resolve_ref(param, spec)
                name = param.get("name")
                if name:
                    columns[f"param.{name}"] = _schema_type(param.get("schema") or {}, spec)

            body_schema = _json_content_schema(operation.get("requestBody") or {}, spec)
            columns.update(_schema_properties(body_schema, spec, prefix="body."))

            response_schema = _json_content_schema(_first_2xx_response(operation), spec)
            columns.update(_schema_properties(response_schema, spec, prefix="response."))

            uri = f"api://{source_name}{path}#{method.lower()}"
            snapshot[uri] = {"kind": "endpoint", "columns": columns}

    for name, schema in ((spec.get("components") or {}).get("schemas") or {}).items():
        snapshot[f"api://{source_name}/components/schemas/{name}"] = {
            "kind": "schema",
            "columns": _schema_properties(schema, spec),
        }

    return snapshot


MAX_PROBE_SAMPLES = 100


def probe_endpoint(url: str, headers: dict | None = None) -> dict:
    """GET one endpoint and infer the payload's schema as {field: type}.

    Only a sample is inspected (the first MAX_PROBE_SAMPLES records of an
    array payload, or the lone object) — probing is a schema check, not a
    data pull.
    """
    import requests

    from metahound.json_schema import generate_schema, schema_types_to_string

    response = requests.get(url, headers=headers or {}, timeout=30)
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, list):
        records = [r for r in payload[:MAX_PROBE_SAMPLES] if isinstance(r, dict)]
    elif isinstance(payload, dict):
        records = [payload]
    else:
        records = []

    if not records:
        return {}
    return {
        name: schema_types_to_string(spec)
        for name, spec in generate_schema(records).items()
    }


def snapshot_from_probes(
    source_name: str,
    probes: list,
    shared_headers: dict | None,
    previous: dict | None,
) -> dict:
    """Probe configured endpoints into snapshot entries of kind "probe".

    A failed probe (HTTP error, non-JSON payload) carries the previous
    scan's entry forward, so a flaky endpoint doesn't masquerade as a
    probe_removed + probe_added churn or a schema change.
    """
    entries = {}
    for probe in probes or []:
        name = probe.get("name")
        url = probe.get("url")
        if not name or not url:
            raise ValueError("each probe requires 'name' and 'url'")

        uri = f"api://{source_name}/probe/{name}"
        headers = {**(shared_headers or {}), **(probe.get("headers") or {})}
        try:
            columns = probe_endpoint(url, headers=headers)
        except Exception as exc:
            logger.warning("Probe %s failed (%s) — keeping previous schema: %s",
                           name, type(exc).__name__, exc)
            prev_entry = (previous or {}).get(uri)
            if prev_entry:
                entries[uri] = prev_entry
            continue

        entries[uri] = {"kind": "probe", "columns": columns}
    return entries
