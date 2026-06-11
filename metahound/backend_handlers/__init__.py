import logging
from sqlalchemy import create_engine, text
from metahound.setup import Sources, Files, Fields, TableMetrics, Tables, Scans
from sqlalchemy.orm import sessionmaker
import datetime
import pandas as pd

logger = logging.getLogger(__name__)


class GenericBackendHandler():
    def __init__(self, connection_uri: str = 'sqlite:///metahound.db'):
        self.connection_uri = connection_uri

        self.connection = self._connect()

    def _connect(self):
        engine = create_engine(self.connection_uri)
        return engine

    def register_scan(self, server: str, last_modified) -> None:
        Session = sessionmaker(bind=self.connection)
        session = Session()

        scan = Scans(server=server, last_modified=last_modified, scan_time=datetime.datetime.utcnow())

        session.add(scan)
        session.commit()
        session.close()


    def get_last_modified(self, server: str):
        Session = sessionmaker(bind=self.connection)
        session = Session()

        last_modified = session.query(Scans).filter_by(server=server).order_by(Scans.scan_time.desc()).first()

        session.close()

        if last_modified is None:
            return datetime.datetime(1970, 1, 1, 0, 0, 0, 0)

        return last_modified.last_modified


    def merge_file_crawl(self, domain: str, protocol: str, file_list: list) -> None:

        Session = sessionmaker(bind=self.connection)
        session = Session()

        source_uri = f"{protocol}://{domain}/"
        source = session.query(Sources).filter_by(uri=source_uri).first()

        if not source:
            source = Sources(name=domain, type=protocol, uri=source_uri)

        for file in file_list:
            file_uri = f"{source_uri}/{file['file']}"

            file_entry = session.query(Files).filter_by(uri=file_uri).first()
            if not file_entry:
                file_entry = Files(name=file['file'], uri=file_uri, filetype='csv', file_encoding='utf-8')

            if file['properties']:
                for column in file['properties'].keys():
                    column_uri = f"{file_uri}/{column}"
                    column_types = '/'.join([f_type for f_type in file['properties'][column]['type'] if f_type != 'null'])
                    column_entry = session.query(Fields).filter_by(uri=column_uri).first()
                    if not column_entry:
                        column_entry = Fields(name=column, type=column_types, uri=column_uri)

                    file_entry.fields.append(column_entry)

            source.files.append(file_entry)

        session.merge(source)
        # Commit the session to write the data to the database
        session.commit()
        session.close()


    def merge_database_crawl(self, domain: str, db_json: dict) -> None:

        Session = sessionmaker(bind=self.connection)
        session = Session()
        source_uri = f"db://{domain}"

        source = session.query(Sources).filter_by(uri=source_uri).first()

        if not source:
            source = Sources(name=domain, type="database", uri=source_uri)


        for schema_name in db_json['schemas'].keys():

            for table_element in db_json['schemas'][schema_name]:
                table_uri = f"db://{domain}/{db_json['database']}/{schema_name}/{table_element['name']}"
                table = session.query(Tables).filter_by(uri=table_uri).first()
                if not table:
                    table = Tables(name=table_element["name"], uri=table_uri, db_name=db_json['database'], schema_name=schema_name)
                else:
                    table.db_name = db_json['database']
                    table.schema_name = schema_name
                source.tables.append(table)

                for column_name in table_element['properties'].keys():
                    column_uri = f"{table_uri}/{column_name}"
                    column = session.query(Fields).filter_by(uri=column_uri).first()
                    if not column:
                        column = Fields(name=column_name, type=table_element['properties'][column_name]['type'], uri=column_uri)
                    else:
                        column.type = table_element['properties'][column_name]['type']
                    table.fields.append(column)


        session.merge(source)
        # Commit the session to write the data to the database
        session.commit()
        session.close()


    def merge_database_stats(self, domain: str, db_json: dict) -> None:

        ts = datetime.datetime.utcnow()

        Session = sessionmaker(bind=self.connection)
        session = Session()
        source_uri = f"db://{domain}"

        source = session.query(Sources).filter_by(uri=source_uri).first()

        if not source:
            logger.debug("creating source")
            source = Sources(name=domain, type="database", uri=source_uri)

        for stat in db_json['stats']:
            table_uri = f"{source_uri}/{db_json['database']}/{stat['schema']}/{stat['table']}"
            table = session.query(Tables).filter_by(uri=table_uri).first()
            if not table:
                table = Tables(name=stat["table"], uri=table_uri, db_name=db_json['database'], schema_name=stat['schema'])
            else:
                table.db_name = db_json['database']
                table.schema_name = stat['schema']
            source.tables.append(table)

            def coerce_float(x):
                try:
                    return float(x)
                except (TypeError, ValueError):
                    return None

            for metric in stat['stats'][0].keys():
                float_value = coerce_float(stat['stats'][0][metric])
                tbl_metric = TableMetrics(
                    metric_name=metric,
                    metric_value=float_value,
                    uri=f"{table_uri}/{metric}",
                    ts=ts
                )
                table.table_metrics.append(tbl_metric)

        session.merge(source)
        session.commit()
        session.close()


    def get_partition(self, partition: str) -> pd.DataFrame:
        query = text(
            "SELECT ts as ds, CAST(metric_value AS FLOAT) as y FROM table_metrics"
            " WHERE uri = :uri ORDER BY ds LIMIT 1000"
        )
        df = pd.read_sql_query(query, self.connection, params={"uri": partition})
        return df

    def get_scan_payload(self) -> dict:
        Session = sessionmaker(bind=self.connection)
        session = Session()

        sources_data = []
        for source in session.query(Sources).all():
            source_dict = {
                "id": source.id,
                "name": source.name,
                "type": source.type,
                "uri": source.uri,
                "tables": [],
                "files": [],
            }

            for table in source.tables:
                table_dict = {
                    "id": table.id,
                    "name": table.name,
                    "uri": table.uri,
                    "db_name": table.db_name,
                    "schema_name": table.schema_name,
                    "fields": [],
                    "metrics": [],
                }
                for field in table.fields:
                    table_dict["fields"].append({
                        "id": field.id,
                        "name": field.name,
                        "type": field.type,
                        "uri": field.uri,
                    })
                for metric in table.table_metrics:
                    table_dict["metrics"].append({
                        "id": metric.id,
                        "metric_name": metric.metric_name,
                        "metric_value": metric.metric_value,
                        "uri": metric.uri,
                        "ts": metric.ts.isoformat() if metric.ts else None,
                    })
                source_dict["tables"].append(table_dict)

            for file in source.files:
                file_dict = {
                    "id": file.id,
                    "name": file.name,
                    "uri": file.uri,
                    "filetype": file.filetype,
                    "file_encoding": file.file_encoding,
                    "fields": [],
                }
                for field in file.fields:
                    file_dict["fields"].append({
                        "id": field.id,
                        "name": field.name,
                        "type": field.type,
                        "uri": field.uri,
                    })
                source_dict["files"].append(file_dict)

            sources_data.append(source_dict)

        session.close()
        return {"sources": sources_data, "cli_version": "2.0.0"}


    def get_partitions(self) -> list:
        query = text("SELECT DISTINCT uri FROM table_metrics")
        partitions = pd.read_sql_query(query, self.connection)
        return list(partitions['uri'])


    def get_status_summary(self) -> dict:
        """Return a summary dict for the status command."""
        Session = sessionmaker(bind=self.connection)
        session = Session()

        sources = session.query(Sources).all()
        summary = []
        for source in sources:
            n_tables = len(source.tables)
            n_files = len(source.files)
            summary.append({
                "name": source.name,
                "type": source.type,
                "tables": n_tables,
                "files": n_files,
            })

        scans = (
            session.query(Scans)
            .order_by(Scans.scan_time.desc())
            .limit(50)
            .all()
        )
        seen = set()
        recent_scans = []
        for scan in scans:
            if scan.server not in seen:
                seen.add(scan.server)
                recent_scans.append({
                    "server": scan.server,
                    "scan_time": scan.scan_time,
                })

        session.close()
        return {"sources": summary, "recent_scans": recent_scans}
