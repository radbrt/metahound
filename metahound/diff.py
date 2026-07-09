"""
Schema diff engine.

Snapshots are plain dicts of the form
    {object_uri: {"kind": "table"|"file", "columns": {column_name: type_string}}}
built from crawl output by the snapshot_from_* helpers. diff_snapshots compares
two snapshots and returns a list of change events:
    {"object_uri": ..., "change_type": ..., "severity": "breaking"|"info", "detail": {...}}
"""
from metahound.json_schema import schema_types_to_string

BREAKING_CHANGE_TYPES = {
    "table_removed",
    "column_removed",
    "column_type_changed",
    "file_schema_changed",
    "fileset_schema_changed",
    "fileset_overdue",
    "endpoint_removed",
    "schema_removed",
}


def make_change(object_uri: str, change_type: str, detail: dict) -> dict:
    severity = "breaking" if change_type in BREAKING_CHANGE_TYPES else "info"
    return {
        "object_uri": object_uri,
        "change_type": change_type,
        "severity": severity,
        "detail": detail,
    }


def snapshot_from_db_crawl(domain: str, db_json: dict) -> dict:
    """Build a snapshot from the crawl JSON produced by a DB scanner's profile_db."""
    snapshot = {}
    for schema_name, tables in db_json["schemas"].items():
        for table in tables:
            uri = f"db://{domain}/{db_json['database']}/{schema_name}/{table['name']}"
            columns = {
                name: schema_types_to_string(spec)
                for name, spec in table["properties"].items()
            }
            snapshot[uri] = {"kind": "table", "columns": columns}
    return snapshot


def snapshot_from_file_crawl(domain: str, protocol: str, file_list: list) -> dict:
    """Build a snapshot from a filesystem crawl's file list.

    URIs match the format used by merge_file_crawl so snapshots and the
    current-state tables refer to the same objects.
    """
    source_uri = f"{protocol}://{domain}/"
    snapshot = {}
    for file in file_list:
        uri = f"{source_uri}/{file['file']}"
        columns = {}
        if file.get("properties"):
            columns = {
                name: schema_types_to_string(spec)
                for name, spec in file["properties"].items()
            }
        snapshot[uri] = {"kind": "file", "columns": columns}
    return snapshot


def diff_snapshots(old: dict, new: dict) -> list:
    """Compare two snapshots and return the list of change events.

    Tables are compared column-by-column; removal of a table is a change.
    Files are immutable once seen, so a file URI reappearing with a different
    non-empty schema is reported as file_schema_changed, and file removals are
    not reported (files routinely get archived off landing zones). Filesets
    behave like files for schema comparison, but their removal (a fileset
    dropped from the config) is reported.
    """
    changes = []

    for uri, obj in new.items():
        kind = obj.get("kind", "table")
        new_columns = obj.get("columns", {})

        if uri not in old:
            changes.append(make_change(uri, f"{kind}_added", {"columns": new_columns}))
            continue

        old_columns = old[uri].get("columns", {})

        if kind in ("file", "fileset"):
            # Only flag when both sides actually have an inferred schema:
            # a scan with get_schemas off yields empty columns, not a change.
            if old_columns and new_columns and old_columns != new_columns:
                changes.append(make_change(uri, f"{kind}_schema_changed", {
                    "old_columns": old_columns,
                    "new_columns": new_columns,
                }))
            continue

        for column, col_type in new_columns.items():
            if column not in old_columns:
                changes.append(make_change(uri, "column_added", {
                    "column": column,
                    "type": col_type,
                }))
            elif old_columns[column] != col_type:
                changes.append(make_change(uri, "column_type_changed", {
                    "column": column,
                    "old_type": old_columns[column],
                    "new_type": col_type,
                }))

        for column, col_type in old_columns.items():
            if column not in new_columns:
                changes.append(make_change(uri, "column_removed", {
                    "column": column,
                    "type": col_type,
                }))

    for uri, obj in old.items():
        kind = obj.get("kind", "table")
        # Files are the only kind whose disappearance is routine (archived
        # off landing zones); everything else vanishing is a change.
        if uri not in new and kind != "file":
            changes.append(make_change(uri, f"{kind}_removed", {
                "columns": obj.get("columns", {}),
            }))

    return changes
