"""
LLM-assisted fileset discovery: the fallback when heuristics can't cluster.

Takes the files heuristic inference left over and asks a small LLM to spot
filename patterns, group the files, and propose human-readable fileset names.

Privacy stance: the prompt contains ONLY filenames and inferred column names/
types — never file contents, connection details, or sample rows.

Trust stance: the model's output is treated as untrusted input. Every
suggested pattern must compile as a fileset glob, every claimed member must
actually match the pattern and exist in the input file list, and clusters
must reach the same minimum size as heuristic inference. Anything that fails
validation silently degrades to the unrecognized-file path — a hallucinated
pattern can never hide a file or invent one.
"""
import json
import logging

from metahound.diff import make_change
from metahound.fileset_inference import MIN_CLUSTER_SIZE
from metahound.filesets import Fileset
from metahound.json_schema import schema_types_to_string

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You group data files that land on a file server into "filesets": recurring \
feeds of the same logical table, e.g. daily order exports. You are given \
filenames (and column names where known). Respond with a JSON object:

{"filesets": [{"name": "...", "pattern": "...", "files": ["...", "..."]}]}

Rules:
- "pattern" is a glob that may use the tokens {date} {time} {seq} {uuid} for \
volatile filename parts, e.g. "orders_{date}.csv" or "export-{uuid}.jsonl"
- "name" is a short snake_case human-readable name for the feed
- Only group files that clearly belong to the same recurring feed (similar \
names AND similar columns when columns are given)
- List every grouped file in "files"; leave genuinely one-off files out
- If nothing groups, respond {"filesets": []}\
"""


def _files_prompt(files: list) -> str:
    lines = []
    for file in files:
        entry = file["file"]
        if file.get("properties"):
            columns = ", ".join(
                f"{name}:{schema_types_to_string(spec)}"
                for name, spec in sorted(file["properties"].items())
            )
            entry += f"  [columns: {columns}]"
        lines.append(entry)
    return "Files:\n" + "\n".join(lines)


def suggest_filesets_llm(
    unmatched_files: list,
    source_name: str,
    provider,
    declared_names: set | None = None,
) -> tuple[list, list]:
    """Ask the provider to cluster the leftover files.

    Returns (events, leftover_files), same contract as heuristic inference.
    Any provider or validation failure returns ([], unmatched_files) — the
    files simply stay unrecognized.
    """
    if not unmatched_files:
        return [], []

    try:
        answer = provider.complete_json(SYSTEM_PROMPT, _files_prompt(unmatched_files))
    except Exception as exc:
        logger.warning("LLM discovery failed (%s) — files stay unrecognized: %s",
                       type(exc).__name__, exc)
        return [], unmatched_files

    suggestions = answer.get("filesets") if isinstance(answer, dict) else None
    if not isinstance(suggestions, list):
        logger.warning("LLM discovery returned unexpected shape — ignoring")
        return [], unmatched_files

    by_name = {f["file"]: f for f in unmatched_files}
    taken = set(declared_names or set())
    events = []
    covered = set()

    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        name = suggestion.get("name")
        pattern = suggestion.get("pattern")
        claimed = suggestion.get("files")
        if not (isinstance(name, str) and isinstance(pattern, str) and isinstance(claimed, list)):
            continue
        if name in taken:
            continue

        try:
            fileset = Fileset(name=name, pattern=pattern)
        except Exception:
            logger.debug("LLM pattern %r did not compile — skipped", pattern)
            continue

        # Untrusted output: keep only claimed files that exist, are not
        # already covered by another suggestion, and really match the pattern.
        members = [
            by_name[f] for f in claimed
            if isinstance(f, str) and f in by_name and f not in covered
            and fileset.matches(f)
        ]
        if len(members) < MIN_CLUSTER_SIZE:
            continue

        taken.add(name)
        covered.update(f["file"] for f in members)
        events.append(make_change(
            f"fileset://{source_name}/{name}",
            "fileset_suggested",
            {
                "name": name,
                "pattern": pattern,
                "file_count": len(members),
                "sample_files": [f["file"] for f in members[:10]],
                "columns": {},
                "via": "llm",
            },
        ))

    leftover = [f for f in unmatched_files if f["file"] not in covered]
    return events, leftover
