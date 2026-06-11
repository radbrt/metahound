import datetime
import logging
import sys
from yaml import safe_load
from dotenv import dotenv_values, load_dotenv
import os
import jinja2
from .setup import run_model_ddls
from metahound.diff import diff_snapshots, snapshot_from_db_crawl, snapshot_from_file_crawl
from metahound.connection_handlers.sftp_connection import SFTPFileSystem
from metahound.connection_handlers.s3_connection import S3FileSystem
from metahound.connection_handlers.az_connection import AZFileSystem
from metahound.file_handlers.parquet_handler import ParquetHandler
from metahound.file_handlers.jsonl_handler import JSONLHandler
from metahound.file_handlers.csv_handler import CSVHandler
from metahound.backend_handlers import GenericBackendHandler
from metahound.db_scanners import GenericDBScanner
import pandas as pd
import click

load_dotenv()

logger = logging.getLogger(__name__)


def parse_spec() -> dict:
    spec_txt = open('metahound.yaml', 'r').read()

    de = dotenv_values(".env")
    jinja_parsed = jinja2.Template(spec_txt).render(de)
    if not os.getenv("METAHOUND_BACKEND_URI"):
        if 'METAHOUND_BACKEND_URI' in de:
            backend_uri = de['METAHOUND_BACKEND_URI'] or 'sqlite:///metahound.db'

            os.environ["METAHOUND_BACKEND_URI"] = backend_uri
        else:
            raise Exception("METAHOUND_BACKEND_URI not set")
    spec = safe_load(jinja_parsed)

    return spec


def _get_backend() -> GenericBackendHandler:
    connection_uri = os.getenv("METAHOUND_BACKEND_URI")
    if connection_uri:
        return GenericBackendHandler(connection_uri=connection_uri)
    return GenericBackendHandler()


def backend_fn() -> None:
    parse_spec()
    run_model_ddls()


def init_fn(foldername: str) -> None:
    """
    Initialize a new metahound project in the specified folder.
    """

    current_script_dir = os.path.dirname(__file__)
    source_file_loc = os.path.join(current_script_dir, 'template', 'metahound.template')
    source_file = open(source_file_loc, 'r')
    source_file_string = source_file.read()
    source_file.close()

    pth = os.path.join(foldername, 'metahound.yaml')
    pwd = os.getcwd()
    if os.path.exists(pth):
        raise Exception(f"metahound.yaml already exists in {foldername}")
    else:
        full_path = os.path.join(pwd, pth)
        os.makedirs(foldername, exist_ok=False)
        # Create file
        with open(full_path, 'w') as f:
            f.write(source_file_string)


def _snapshot_and_diff(
    backend: GenericBackendHandler,
    scan_id: int,
    source_uri: str,
    previous: dict | None,
    snapshot: dict,
) -> list:
    """Persist a snapshot and record changes against the previous one.

    The first scan of a source establishes the baseline: the snapshot is saved
    but no change events are recorded (everything would be "added").
    """
    backend.save_snapshot(scan_id, source_uri, snapshot)
    if previous is None:
        return []
    changes = diff_snapshots(previous, snapshot)
    backend.record_changes(scan_id, source_uri, changes)
    return changes


def _scan_filesystem_source(
    source_name: str,
    protocol: str,
    filesystem,
    backend: GenericBackendHandler,
    get_schemas: bool,
) -> None:
    """Scan a filesystem source (sftp, s3, az) and persist results."""
    all_files = filesystem.get_files()
    highwater = backend.get_last_modified(server=source_name)
    new_files = [f['name'] for f in all_files if f['mtime'] > highwater]
    schemas = [handle_file(file_name, filesystem, get_schemas) for file_name in new_files]
    backend.merge_file_crawl(domain=source_name, protocol=protocol, file_list=schemas)
    last_modified = filesystem.get_last_modified()

    # Filesystem scans only see files above the highwater mark, so the new
    # snapshot is the previous one plus what this scan found.
    source_uri = f"{protocol}://{source_name}/"
    previous = backend.get_latest_snapshot(source_uri)
    snapshot = dict(previous or {})
    snapshot.update(snapshot_from_file_crawl(source_name, protocol, schemas))

    scan_id = backend.register_scan(server=source_name, last_modified=last_modified)
    _snapshot_and_diff(backend, scan_id, source_uri, previous, snapshot)


def _make_db_scanners(source: dict) -> list:
    """Return (db_label, scanner) pairs for a database-type source."""
    config = source['connection']

    match source["type"]:
        case "snowflake":
            from metahound.db_scanners.snowflake_scanner import SnowflakeScanner
            return [(db, SnowflakeScanner(database=db, **config)) for db in source["databases"]]
        case "database":
            return [(db, GenericDBScanner(database=db, **config)) for db in source["databases"]]
        case "bigquery":
            from metahound.db_scanners.bigquery_scanner import BigQueryScanner
            return [(ds, BigQueryScanner(dataset=ds, **config)) for ds in source.get("datasets", [])]
        case "oracle":
            from metahound.db_scanners.oracle_scanner import OracleScanner
            return [(config.get("service_name", source['name']), OracleScanner(**config))]
        case "mssql":
            from metahound.db_scanners.mssql_scanner import MSSQLScanner
            return [(db, MSSQLScanner(database=db, **config)) for db in source["databases"]]
        case _:
            raise NotImplementedError(f"Source type {source['type']} not implemented")


def _scan_database_source(source: dict, backend: GenericBackendHandler, no_stats: bool) -> None:
    """Scan a database-type source: crawl, stats, snapshot and diff."""
    do_analyze = source.get("analyze", True) and not no_stats

    snapshot = {}
    for db_label, scanner in _make_db_scanners(source):
        catalog, stats = scanner.profile_db(db_label, do_analyze)
        backend.merge_database_crawl(domain=source['name'], db_json=catalog)
        if do_analyze:
            backend.merge_database_stats(domain=source['name'], db_json=stats)
        snapshot.update(snapshot_from_db_crawl(source['name'], catalog))

    source_uri = f"db://{source['name']}"
    previous = backend.get_latest_snapshot(source_uri)
    scan_id = backend.register_scan(server=source['name'], last_modified=datetime.datetime.utcnow())
    _snapshot_and_diff(backend, scan_id, source_uri, previous, snapshot)


def _scan_source(source: dict, backend: GenericBackendHandler, no_stats: bool) -> None:
    logger.info(f"Scanning {source['type']} {source['name']}")

    match source["type"]:

        case "snowflake" | "database" | "bigquery" | "oracle" | "mssql":
            _scan_database_source(source, backend, no_stats)

        case "sftp":
            get_schemas = source.get("get_schemas", False)
            filesystem = SFTPFileSystem(
                host=source['connection']['host'],
                username=source['connection']['username'],
                password=source['connection']['password'],
                search_prefix=source['search_prefix'])
            _scan_filesystem_source(source['name'], 'sftp', filesystem, backend, get_schemas)

        case "s3":
            get_schemas = source.get("get_schemas", False)
            filesystem = S3FileSystem(search_prefix=source['bucket'], storage_options=source['connection'])
            _scan_filesystem_source(source['name'], 's3', filesystem, backend, get_schemas)

        case "az":
            get_schemas = source.get("get_schemas", False)
            filesystem = AZFileSystem(search_prefix=source['path'], storage_options=source['connection'])
            _scan_filesystem_source(source['name'], 'az', filesystem, backend, get_schemas)

        case _:
            raise NotImplementedError("Source type not implemented")


def scan_fn(select: str | None, no_stats: bool) -> None:
    """
    Main scan function, parses the metahound.yaml file, scans the specified sources
    and writes the results to the backend.

    One failing source does not abort the run; failures are summarized at the
    end and the command exits non-zero if any source failed.
    """

    project_spec = parse_spec()
    backend = _get_backend()

    sources = project_spec["sources"]
    if select:
        selected = {name.strip() for name in select.split(",")}
        sources = [s for s in sources if s.get("name") in selected]
        missing = selected - {s.get("name") for s in sources}
        if missing:
            raise click.ClickException(f"Unknown source(s) in --select: {', '.join(sorted(missing))}")

    failures = []
    for source in sources:
        try:
            _scan_source(source, backend, no_stats)
        except Exception as exc:
            logger.exception(f"Scan failed for source {source.get('name', '?')}")
            failures.append((source.get('name', '?'), exc))

    if failures:
        summary = ", ".join(f"{name} ({exc})" for name, exc in failures)
        raise click.ClickException(f"{len(failures)} source(s) failed to scan: {summary}")


def handle_file(file_name: str, filesystem, get_schemas: bool) -> dict:

    file_stream = filesystem.get_file(file_name)

    if file_name.endswith('.csv'):
        csv_handler = CSVHandler(file_stream, file_name, get_schema=get_schemas)
        return csv_handler.get_file_metadata()

    elif file_name.endswith('.parquet'):
        pq_handler = ParquetHandler(file_stream, file_name, get_schema=get_schemas)
        return pq_handler.get_file_metadata()

    elif file_name.endswith('.jsonl'):
        jsonl_handler = JSONLHandler(file_stream, file_name, get_schema=get_schemas)
        return jsonl_handler.get_file_metadata()

    else:
        return {"file": file_name, "properties": {}}


def push_fn(api_url: str, api_token: str) -> None:
    """Serialize local DB and POST it to the Metahound server ingest endpoint."""
    import hashlib
    import json
    import requests

    backend = _get_backend()

    if not api_token:
        api_token = os.getenv("METAHOUND_API_TOKEN")
    if not api_token:
        raise ValueError("No API token provided. Set METAHOUND_API_TOKEN or use --token.")

    if not api_url:
        api_url = os.getenv("METAHOUND_API_URL")
    if not api_url:
        raise ValueError("No API URL provided. Set METAHOUND_API_URL or use --api-url.")

    payload = backend.get_scan_payload()

    # Hash the sources content so the cloud can detect duplicate pushes.
    # cli_version is excluded so a version upgrade alone doesn't bypass dedup.
    push_hash = hashlib.sha256(
        json.dumps(payload["sources"], sort_keys=True, default=str).encode()
    ).hexdigest()
    payload["push_hash"] = push_hash

    response = requests.post(
        f"{api_url}/api/v1/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {api_token}"},
    )
    response.raise_for_status()
    result = response.json()
    if result.get("duplicate"):
        logger.info("Push skipped: no new scan data since last push")
        click.echo("No new scan data since last push — nothing pushed.")
    else:
        logger.info(f"Push successful: {result}")
        click.echo(f"Push successful: {result}")


def _set_env_value(env_path: str, key: str, value: str) -> None:
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                break
    if not found:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)


def token_set_fn(token: str) -> None:
    """Write METAHOUND_API_TOKEN to the local .env file."""
    env_path = os.path.join(os.getcwd(), ".env")
    _set_env_value(env_path, "METAHOUND_API_TOKEN", token)
    click.echo("Token saved to .env")


def url_set_fn(api_url: str) -> None:
    """Write METAHOUND_API_URL to the local .env file."""
    env_path = os.path.join(os.getcwd(), ".env")
    _set_env_value(env_path, "METAHOUND_API_URL", api_url)
    click.echo("API URL saved to .env")


def warnings_fn(algorithm: str, threshold: float | None = None) -> None:
    """
    Print warnings about the current project
    """
    project_spec = parse_spec()
    backend = _get_backend()

    global_anomaly = project_spec.get("anomaly", {})
    global_threshold = global_anomaly.get("threshold", 3.0)
    global_algorithm = global_anomaly.get("algorithm", algorithm)

    partitions = backend.get_partitions()

    n_outlier_partitions = 0
    for partition in partitions:
        df = backend.get_partition(partition)
        df = df.dropna()

        if len(df) > 1:
            # Determine per-partition algorithm and threshold from spec
            # (partitions are URIs; we use the global spec config here)
            effective_algorithm = global_algorithm
            effective_threshold = threshold if threshold is not None else global_threshold

            if effective_algorithm == 'prophet':
                from metahound.outlierdetection import OutlierDetector
                analyzer = OutlierDetector()
            elif effective_algorithm == 'zindex':
                from metahound.outlierdetection import zIndex
                analyzer = zIndex(threshold=effective_threshold)
            else:
                raise NotImplementedError("Algorithm not implemented")

            outliers = analyzer.get_outliers_in_df(df)
        else:
            outliers = pd.DataFrame()

        if len(outliers) > 1:
            click.echo(f"Outliers found in metric URI {partition}")
            click.echo(outliers.to_markdown(index=False, floatfmt=".2f", tablefmt="pretty"))
            n_outlier_partitions += 1

    if n_outlier_partitions == 0:
        click.echo("No outliers found")


def _format_change_detail(change_type: str, detail: dict) -> str:
    match change_type:
        case "column_added":
            return f"{detail.get('column')} ({detail.get('type')})"
        case "column_removed":
            return f"{detail.get('column')} ({detail.get('type')})"
        case "column_type_changed":
            return f"{detail.get('column')}: {detail.get('old_type')} -> {detail.get('new_type')}"
        case "file_schema_changed":
            old_cols = set(detail.get('old_columns', {}))
            new_cols = set(detail.get('new_columns', {}))
            parts = []
            if new_cols - old_cols:
                parts.append(f"+{', +'.join(sorted(new_cols - old_cols))}")
            if old_cols - new_cols:
                parts.append(f"-{', -'.join(sorted(old_cols - new_cols))}")
            return "; ".join(parts) or "column types changed"
        case "table_added" | "table_removed" | "file_added":
            n_columns = len(detail.get('columns', {}))
            return f"{n_columns} column(s)" if n_columns else ""
        case _:
            return ""


def changes_fn(since: str | None, fail_on: str | None) -> None:
    """
    Print schema changes recorded by previous scans.

    Without --since, shows changes from the most recent scan of each source.
    With --fail-on, exits non-zero when matching changes exist, so the command
    can gate ingest pipelines (Airflow/Dagster pre-task, cron, CI).
    """
    from tabulate import tabulate

    backend = _get_backend()

    since_dt = None
    if since:
        try:
            since_dt = datetime.datetime.fromisoformat(since)
        except ValueError:
            raise click.ClickException(f"--since must be an ISO timestamp, got: {since}")

    changes = backend.get_changes(since=since_dt)

    if not changes:
        click.echo("No schema changes recorded")
    else:
        rows = [
            [
                change["ts"].strftime("%Y-%m-%d %H:%M") if change["ts"] else "—",
                change["severity"],
                change["change_type"],
                change["object_uri"],
                _format_change_detail(change["change_type"], change["detail"]),
            ]
            for change in changes
        ]
        click.echo(tabulate(rows, headers=["Time", "Severity", "Change", "Object", "Detail"], tablefmt="simple"))

        n_breaking = sum(1 for c in changes if c["severity"] == "breaking")
        click.echo(f"\n{len(changes)} change(s), {n_breaking} breaking")

    if fail_on == "any" and changes:
        sys.exit(1)
    if fail_on == "breaking" and any(c["severity"] == "breaking" for c in changes):
        sys.exit(1)


def status_fn() -> None:
    """Print a summary of what's stored in the backend."""
    from tabulate import tabulate

    backend = _get_backend()
    summary = backend.get_status_summary()

    sources = summary["sources"]
    recent_scans = summary["recent_scans"]

    click.echo(f"\nSources ({len(sources)})")
    if sources:
        rows = [[s["name"], s["type"], s["tables"], s["files"]] for s in sources]
        click.echo(tabulate(rows, headers=["Name", "Type", "Tables", "Files"], tablefmt="simple"))
    else:
        click.echo("  (none)")

    click.echo("\nRecent scans")
    if recent_scans:
        scan_rows = [
            [s["server"], s["scan_time"].strftime("%Y-%m-%d %H:%M") if s["scan_time"] else "—"]
            for s in recent_scans
        ]
        click.echo(tabulate(scan_rows, headers=["Source", "Last scan"], tablefmt="simple"))
    else:
        click.echo("  (no scans recorded)")
