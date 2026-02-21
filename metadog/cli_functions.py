import logging
from yaml import safe_load
from dotenv import dotenv_values, load_dotenv
import os
import jinja2
from .setup import run_model_ddls
from metadog.connection_handlers.sftp_connection import SFTPFileSystem
from metadog.connection_handlers.s3_connection import S3FileSystem
from metadog.connection_handlers.az_connection import AZFileSystem
from metadog.file_handlers.parquet_handler import ParquetHandler
from metadog.file_handlers.jsonl_handler import JSONLHandler
from metadog.file_handlers.csv_handler import CSVHandler
from metadog.backend_handlers import GenericBackendHandler
from metadog.db_scanners import GenericDBScanner
import pandas as pd
import click

load_dotenv()

logger = logging.getLogger(__name__)


def parse_spec() -> dict:
    spec_txt = open('metadog.yaml', 'r').read()

    de = dotenv_values(".env")
    jinja_parsed = jinja2.Template(spec_txt).render(de)
    if not os.getenv("METADOG_BACKEND_URI"):
        if 'METADOG_BACKEND_URI' in de:
            backend_uri = de['METADOG_BACKEND_URI'] or 'sqlite:///metadog.db'

            os.environ["METADOG_BACKEND_URI"] = backend_uri
        else:
            raise Exception("METADOG_BACKEND_URI not set")
    spec = safe_load(jinja_parsed)

    return spec


def _get_backend() -> GenericBackendHandler:
    connection_uri = os.getenv("METADOG_BACKEND_URI")
    if connection_uri:
        return GenericBackendHandler(connection_uri=connection_uri)
    return GenericBackendHandler()


def backend_fn() -> None:
    parse_spec()
    run_model_ddls()


def init_fn(foldername: str) -> None:
    """
    Initialize a new metadog project in the specified folder.
    """

    current_script_dir = os.path.dirname(__file__)
    source_file_loc = os.path.join(current_script_dir, 'template', 'metadog.template')
    source_file = open(source_file_loc, 'r')
    source_file_string = source_file.read()
    source_file.close()

    pth = os.path.join(foldername, 'metadog.yaml')
    pwd = os.getcwd()
    if os.path.exists(pth):
        raise Exception(f"metadog.yaml already exists in {foldername}")
    else:
        full_path = os.path.join(pwd, pth)
        os.makedirs(foldername, exist_ok=False)
        # Create file
        with open(full_path, 'w') as f:
            f.write(source_file_string)


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
    backend.register_scan(server=source_name, last_modified=last_modified)


def scan_fn(select: str | None, no_stats: bool) -> None:
    """
    Main scan function, parses the metadog.yaml file, scans the specified sources
    and writes the results to the backend
    """

    project_spec = parse_spec()
    backend = _get_backend()

    for source in project_spec["sources"]:

        match source["type"]:

            case "snowflake":
                logger.info(f"Scanning snowflake {source['name']}")
                from metadog.db_scanners.snowflake_scanner import SnowflakeScanner
                for db in source["databases"]:
                    config = source['connection']
                    do_analyze = source.get("analyze", True) and not no_stats
                    db_scanner = SnowflakeScanner(database=db, **config)
                    catalog, stats = db_scanner.profile_db(db, do_analyze)

                    backend.merge_database_crawl(domain=source['name'], db_json=catalog)
                    if do_analyze:
                        backend.merge_database_stats(domain=source['name'], db_json=stats)

            case "database":
                logger.info(f"Scanning database {source['name']}")
                for db in source["databases"]:
                    config = source['connection']
                    do_analyze = source.get("analyze", True) and not no_stats
                    db_scanner = GenericDBScanner(database=db, **config)

                    catalog, stats = db_scanner.profile_db(db, do_analyze)
                    backend.merge_database_crawl(domain=source['name'], db_json=catalog)
                    if do_analyze:
                        backend.merge_database_stats(domain=source['name'], db_json=stats)

            case "bigquery":
                logger.info(f"Scanning BigQuery {source['name']}")
                from metadog.db_scanners.bigquery_scanner import BigQueryScanner
                for dataset in source.get("datasets", []):
                    config = source['connection']
                    do_analyze = source.get("analyze", True) and not no_stats
                    db_scanner = BigQueryScanner(dataset=dataset, **config)
                    catalog, stats = db_scanner.profile_db(dataset, do_analyze)
                    backend.merge_database_crawl(domain=source['name'], db_json=catalog)
                    if do_analyze:
                        backend.merge_database_stats(domain=source['name'], db_json=stats)

            case "oracle":
                logger.info(f"Scanning Oracle {source['name']}")
                from metadog.db_scanners.oracle_scanner import OracleScanner
                config = source['connection']
                do_analyze = source.get("analyze", True) and not no_stats
                db_scanner = OracleScanner(**config)
                catalog, stats = db_scanner.profile_db(config.get("service_name", source['name']), do_analyze)
                backend.merge_database_crawl(domain=source['name'], db_json=catalog)
                if do_analyze:
                    backend.merge_database_stats(domain=source['name'], db_json=stats)

            case "mssql":
                logger.info(f"Scanning MSSQL {source['name']}")
                from metadog.db_scanners.mssql_scanner import MSSQLScanner
                for db in source["databases"]:
                    config = source['connection']
                    do_analyze = source.get("analyze", True) and not no_stats
                    db_scanner = MSSQLScanner(database=db, **config)
                    catalog, stats = db_scanner.profile_db(db, do_analyze)
                    backend.merge_database_crawl(domain=source['name'], db_json=catalog)
                    if do_analyze:
                        backend.merge_database_stats(domain=source['name'], db_json=stats)

            case "sftp":
                logger.info(f"Scanning sftp {source['name']}")
                get_schemas = source.get("get_schemas", False)
                filesystem = SFTPFileSystem(
                    host=source['connection']['host'],
                    username=source['connection']['username'],
                    password=source['connection']['password'],
                    search_prefix=source['search_prefix'])
                _scan_filesystem_source(source['name'], 'sftp', filesystem, backend, get_schemas)

            case "s3":
                logger.info(f"Scanning s3 {source['name']}")
                get_schemas = source.get("get_schemas", False)
                filesystem = S3FileSystem(search_prefix=source['bucket'], storage_options=source['connection'])
                _scan_filesystem_source(source['name'], 's3', filesystem, backend, get_schemas)

            case "az":
                logger.info(f"Scanning AZ {source['name']}")
                get_schemas = source.get("get_schemas", False)
                filesystem = AZFileSystem(search_prefix=source['path'], storage_options=source['connection'])
                _scan_filesystem_source(source['connection']['account_name'], 'az', filesystem, backend, get_schemas)

            case _:
                raise NotImplementedError("Source type not implemented")


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
    """Serialize local DB and POST it to the Metadog server ingest endpoint."""
    import requests

    backend = _get_backend()

    if not api_token:
        api_token = os.getenv("METADOG_API_TOKEN")
    if not api_token:
        raise ValueError("No API token provided. Set METADOG_API_TOKEN or use --token.")

    if not api_url:
        api_url = os.getenv("METADOG_API_URL")
    if not api_url:
        raise ValueError("No API URL provided. Set METADOG_API_URL or use --api-url.")

    payload = backend.get_scan_payload()
    response = requests.post(
        f"{api_url}/api/v1/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {api_token}"},
    )
    response.raise_for_status()
    result = response.json()
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
    """Write METADOG_API_TOKEN to the local .env file."""
    env_path = os.path.join(os.getcwd(), ".env")
    _set_env_value(env_path, "METADOG_API_TOKEN", token)
    click.echo("Token saved to .env")


def url_set_fn(api_url: str) -> None:
    """Write METADOG_API_URL to the local .env file."""
    env_path = os.path.join(os.getcwd(), ".env")
    _set_env_value(env_path, "METADOG_API_URL", api_url)
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
                from metadog.outlierdetection import OutlierDetector
                analyzer = OutlierDetector()
            elif effective_algorithm == 'zindex':
                from metadog.outlierdetection import zIndex
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
