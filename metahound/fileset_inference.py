"""
Fileset inference: suggest fileset declarations for unrecognized files.

Filenames are normalized into templates by replacing volatile parts (dates,
times, UUIDs, sequence numbers) with the {date}/{time}/{uuid}/{seq} tokens the
declared-fileset engine already understands. Files sharing a template are
clustered, membership is confirmed by schema fingerprint (majority wins), and
each cluster of at least MIN_CLUSTER_SIZE files becomes one fileset_suggested
change event whose detail carries a ready-to-paste fileset declaration.

Suggestions are findings, not configuration: nothing is created until the
user adds the pattern to metahound.yaml. Files that don't cluster — or whose
schema disagrees with their cluster — stay individual unrecognized_file
warnings, so inference can only reduce noise, never hide a file.
"""
import os
import re
from collections import Counter

from metahound.diff import make_change
from metahound.json_schema import schema_types_to_string

MIN_CLUSTER_SIZE = 2

# Ordered: most-specific first, so a UUID is not shredded into {seq} runs and
# a compact timestamp is not half-eaten by the date pattern.
_NORMALIZE_STEPS = [
    ("{uuid}", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
    ("{date}{time}", re.compile(r"\d{4}[-_.]?\d{2}[-_.]?\d{2}T?\d{2}[-_.:]?\d{2}[-_.:]?\d{2}")),
    ("{date}", re.compile(r"\d{4}[-_.]?\d{2}[-_.]?\d{2}")),
    ("{time}", re.compile(r"\d{2}[-_.:]\d{2}[-_.:]\d{2}")),
    ("{seq}", re.compile(r"\d+")),
]


def normalize_filename(path: str) -> str:
    """Reduce a filename to its template: orders_2026-07-09.csv → orders_{date}.csv."""
    template = os.path.basename(path)
    for token, pattern in _NORMALIZE_STEPS:
        template = pattern.sub(token, template)
    return template


def _suggest_name(template: str, taken: set) -> str:
    """Derive a fileset name from a template: orders_{date}.csv → orders."""
    stem = template.rsplit(".", 1)[0]
    stem = re.sub(r"\{(date|time|seq|uuid)\}", "", stem)
    stem = re.sub(r"[^0-9a-zA-Z]+$", "", stem)
    stem = re.sub(r"^[^0-9a-zA-Z]+", "", stem)
    name = stem or "fileset"

    candidate = name
    counter = 2
    while candidate in taken:
        candidate = f"{name}_{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def _fingerprint(file: dict) -> tuple | None:
    """Schema fingerprint: sorted (column, type) pairs, or None if no schema."""
    if not file.get("properties"):
        return None
    return tuple(sorted(
        (name, schema_types_to_string(spec))
        for name, spec in file["properties"].items()
    ))


def infer_filesets(
    unmatched_files: list,
    source_name: str,
    declared_names: set | None = None,
) -> tuple[list, list]:
    """Cluster unmatched files into suggested filesets.

    Returns (events, leftover_files): one fileset_suggested change event per
    confirmed cluster, and the files no suggestion covers — the caller should
    keep reporting those as unrecognized.
    """
    clusters: dict[str, list] = {}
    for file in unmatched_files:
        template = normalize_filename(file["file"])
        clusters.setdefault(template, []).append(file)

    taken = set(declared_names or set())
    events = []
    leftover = []

    token_re = re.compile(r"\{(date|time|seq|uuid)\}")
    for template, files in sorted(clusters.items()):
        # A template without volatile tokens is a static filename — the same
        # file seen in several places, not a recurring feed.
        if len(files) < MIN_CLUSTER_SIZE or not token_re.search(template):
            leftover.extend(files)
            continue

        # Confirm membership by schema fingerprint: the majority schema is the
        # cluster's; disagreeing files degrade to unrecognized. Files without
        # an inferred schema (schemas off, unhandled format) ride along on the
        # filename match alone.
        fingerprints = [fp for fp in (_fingerprint(f) for f in files) if fp is not None]
        majority = Counter(fingerprints).most_common(1)[0][0] if fingerprints else None

        members, outliers = [], []
        for file in files:
            fp = _fingerprint(file)
            if fp is None or fp == majority:
                members.append(file)
            else:
                outliers.append(file)
        leftover.extend(outliers)

        if len(members) < MIN_CLUSTER_SIZE:
            leftover.extend(members)
            continue

        name = _suggest_name(template, taken)
        detail = {
            "name": name,
            "pattern": template,
            "file_count": len(members),
            "sample_files": [f["file"] for f in members[:10]],
            "columns": dict(majority) if majority else {},
        }
        events.append(make_change(
            f"fileset://{source_name}/{name}", "fileset_suggested", detail,
        ))

    return events, leftover
