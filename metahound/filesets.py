"""
Declared filesets: logical tables over files on filesystem sources.

A fileset groups files sharing a filename pattern (a glob, a regex, or a glob
with {date}-style tokens) into one logical table with a canonical schema. The
canonical schema is the first inferred schema seen among matched files and is
persisted in the source snapshot under a fileset:// URI, so it is stable
across scans. Matched files are validated against it; a deviation is a
breaking file_schema_changed event, and files matching no declared fileset
are reported as unrecognized_file findings. Both flow through the same change
stream as the schema diff engine, so `metahound changes --fail-on breaking`
gates on them with no extra configuration.
"""
import fnmatch
import os
import re

from metahound.diff import make_change
from metahound.json_schema import schema_types_to_string

TOKEN_PATTERNS = {
    "date": r"\d{4}[-_.]?\d{2}[-_.]?\d{2}",
    "time": r"\d{2}[-_.:]?\d{2}[-_.:]?\d{2}",
    "seq": r"\d+",
    "uuid": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
}

_TOKEN_RE = re.compile(r"\{(" + "|".join(TOKEN_PATTERNS) + r")\}")


def _compile_pattern(pattern: str) -> re.Pattern:
    """Compile a glob pattern that may contain {date}/{time}/{seq}/{uuid} tokens."""
    tokens = []

    def _placeholder(match: re.Match) -> str:
        tokens.append(TOKEN_PATTERNS[match.group(1)])
        return f"__MHTOKEN{len(tokens) - 1}__"

    templated = _TOKEN_RE.sub(_placeholder, pattern)
    regex = fnmatch.translate(templated)
    for i, token_regex in enumerate(tokens):
        regex = regex.replace(f"__MHTOKEN{i}__", token_regex)
    return re.compile(regex)


class Fileset:
    def __init__(self, name: str, pattern: str | None = None, regex: str | None = None):
        if not name:
            raise ValueError("fileset requires a name")
        if bool(pattern) == bool(regex):
            raise ValueError(f"fileset '{name}' requires exactly one of 'pattern' or 'regex'")
        self.name = name
        self.spec = pattern or regex
        # Patterns without a path separator match against the basename, so
        # "orders_*.csv" finds files regardless of which directory they land in.
        self._match_full_path = "/" in self.spec
        self._regex = re.compile(regex) if regex else _compile_pattern(pattern)

    def matches(self, path: str) -> bool:
        candidate = path if self._match_full_path else os.path.basename(path)
        return self._regex.fullmatch(candidate) is not None


def parse_filesets(config: list | None) -> list:
    """Build Fileset objects from the `filesets` list of a source config."""
    filesets = []
    seen = set()
    for entry in config or []:
        if not isinstance(entry, dict):
            raise ValueError(f"fileset entries must be mappings, got: {entry!r}")
        unknown = set(entry) - {"name", "pattern", "regex"}
        if unknown:
            raise ValueError(
                f"unknown key(s) in fileset '{entry.get('name', '?')}': {', '.join(sorted(unknown))}"
            )
        fileset = Fileset(
            name=entry.get("name"),
            pattern=entry.get("pattern"),
            regex=entry.get("regex"),
        )
        if fileset.name in seen:
            raise ValueError(f"duplicate fileset name: {fileset.name}")
        seen.add(fileset.name)
        filesets.append(fileset)
    return filesets


def fileset_uri(source_name: str, fileset_name: str) -> str:
    return f"fileset://{source_name}/{fileset_name}"


def evaluate_filesets(
    filesets: list,
    file_list: list,
    previous: dict | None,
    source_name: str,
    protocol: str,
    alert_unrecognized: bool = True,
) -> tuple[dict, list]:
    """Match crawled files against declared filesets.

    Returns (snapshot_entries, change_events): snapshot entries keyed by
    fileset:// URI carrying each fileset's canonical schema, and events for
    schema mismatches (breaking) and unrecognized files (info). Files with no
    inferred schema (get_schemas off, or unhandled formats) still count for
    recognition but are not schema-validated. The first file in a fileset
    lands silently — its schema becomes the canonical baseline.
    """
    source_uri = f"{protocol}://{source_name}/"

    canonical = {}
    for fileset in filesets:
        prev_entry = (previous or {}).get(fileset_uri(source_name, fileset.name), {})
        canonical[fileset.name] = dict(prev_entry.get("columns") or {})

    events = []
    for file in file_list:
        file_name = file["file"]
        columns = {}
        if file.get("properties"):
            columns = {
                name: schema_types_to_string(spec)
                for name, spec in file["properties"].items()
            }

        fileset = next((f for f in filesets if f.matches(file_name)), None)
        file_object_uri = f"{source_uri}/{file_name}"

        if fileset is None:
            if alert_unrecognized:
                events.append(make_change(file_object_uri, "unrecognized_file", {
                    "file": file_name,
                    "declared_filesets": [f.name for f in filesets],
                }))
            continue

        if not columns:
            continue
        if not canonical[fileset.name]:
            canonical[fileset.name] = columns
        elif columns != canonical[fileset.name]:
            events.append(make_change(file_object_uri, "file_schema_changed", {
                "fileset": fileset.name,
                "old_columns": canonical[fileset.name],
                "new_columns": columns,
            }))

    snapshot_entries = {
        fileset_uri(source_name, fileset.name): {
            "kind": "fileset",
            "columns": canonical[fileset.name],
            "pattern": fileset.spec,
        }
        for fileset in filesets
    }
    return snapshot_entries, events
