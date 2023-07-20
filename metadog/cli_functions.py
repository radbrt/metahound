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
from metadog.db_scanners.snowflake_scanner import SnowflakeScanner
import pandas as pd

from metadog.outlierdetection import OutlierDetector


load_dotenv()


def parse_spec():
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


def backend_fn():
    spec = parse_spec()
    run_model_ddls()


def init_fn(foldername):
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


def scan_fn(select, no_stats):
    """
    Main scan function, parses the metadog.yaml file, scans the specified sources
    and writes the results to the backend
    """
    
    project_spec = parse_spec()
    connection_uri = os.getenv("METADOG_BACKEND_URI")
    if connection_uri:
        backend = GenericBackendHandler(connection_uri=connection_uri)
    else:
        backend = GenericBackendHandler()


    for source in project_spec["sources"]:

        match source["type"]:

            case "snowflake":
                print(f"Scanning snowflake {source['name']}")
                for db in source["databases"]:
                    config = source['connection']
                    do_analyze = source.get("analyze", True) and not no_stats
                    db_scanner = SnowflakeScanner(database=db, **config)
                    catalog, stats = db_scanner.profile_db(db, do_analyze)

                    backend.merge_database_crawl(domain=source['name'], db_json=catalog)
                    if do_analyze:
                        backend.merge_database_stats(domain=source['name'], db_json=stats)

            case "database" :
                print(f"Scanning database {source['name']}")
                for db in source["databases"]:
                    config = source['connection']
                    do_analyze = source.get("analyze", True) and not no_stats
                    db_scanner = GenericDBScanner(database=db, **config)

                    catalog, stats = db_scanner.profile_db(db, do_analyze)
                    backend.merge_database_crawl(domain=source['name'], db_json=catalog)
                    if do_analyze:
                        backend.merge_database_stats(domain=source['name'], db_json=stats)

            case "sftp":
                print(f"Scanning sftp {source['name']}")
                get_schemas = source.get("get_schemas", False)
                filesystem = SFTPFileSystem(
                    host=source['connection']['host'], 
                    username=source['connection']['username'], 
                    password=source['connection']['password'],
                    search_prefix=source['search_prefix'])
                
                all_files = filesystem.get_files()
                highwater = backend.get_last_modified(server=source['name'])
                files = [f['name'] for f in all_files if f['mtime'] > highwater]
                schemas = []
                for file_name in files:
                    schema = handle_file(file_name, filesystem, get_schemas)
                    schemas.append(schema)
                
                file_domain = filesystem.uri
                backend.merge_file_crawl(domain=source['name'], protocol='sftp', file_list=schemas)
                last_modified = filesystem.get_last_modified()
                backend.register_scan(server=source['name'], last_modified=last_modified)

            case "s3":
                print(f"Scanning s3 {source['name']}")
                get_schemas = source.get("get_schemas", False)
                filesystem = S3FileSystem(search_prefix=source['bucket'], storage_options=source['connection'])

                ####### ABSTRACT AWAY #######
                all_files = filesystem.get_files()
                highwater = backend.get_last_modified(server=source['name'])
                files = [f['name'] for f in all_files if f['mtime'] > highwater]
                schemas = []
                for file_name in files:
                    schema = handle_file(file_name, filesystem, get_schemas)
                    schemas.append(schema)
                
                file_domain = filesystem.uri
                backend.merge_file_crawl(domain=source['name'], protocol='s3', file_list=schemas)
                last_modified = filesystem.get_last_modified()
                backend.register_scan(server=source['name'], last_modified=last_modified)

            case "az":
                print(f"Scanning AZ {source['name']}")
                get_schemas = source.get("get_schemas", False)
                filesystem = AZFileSystem(search_prefix=source['path'], storage_options=source['connection'])

                all_files = filesystem.get_files()
                highwater = backend.get_last_modified(server=source['name'])
                files = [f['name'] for f in all_files if f['mtime'] > highwater]
                schemas = []
                for file_name in files:
                    schema = handle_file(file_name, filesystem, get_schemas)
                    schemas.append(schema)

                file_domain = filesystem.uri
                backend.merge_file_crawl(domain=source['connection']['account_name'], protocol='az', file_list=schemas)
                last_modified = filesystem.get_last_modified()
                backend.register_scan(server=source['name'], last_modified=last_modified)

            case _:
                raise NotImplementedError("Source type not implemented")


def handle_file(file_name, filesystem, get_schemas):
    
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
        return {"file": file_name, "properties": {} }


def warnings_fn():
    """
    Print warnings about the current project
    """
    project_spec = parse_spec()
    connection_uri = os.getenv("METADOG_BACKEND_URI")
    if connection_uri:
        backend = GenericBackendHandler(connection_uri=connection_uri)
    else:
        backend = GenericBackendHandler()

    analyzer = OutlierDetector()
    partitions = backend.get_partitions()

    n_outier_partitions = 0
    for partition in partitions:
        df = backend.get_partition(partition)
        df.dropna(inplace=True)

        if len(df) > 1:
            outliers = analyzer.get_outliers_in_df(df)
        else:
            outliers = pd.DataFrame()

        if len(outliers) > 1:
            print(f"Outliers found in metric URI {partition}")
            print(outliers.to_markdown( index=False, floatfmt=".2f", tablefmt="pretty"))
            n_outier_partitions += 1

    if n_outier_partitions == 0:
        print("No outliers found")
