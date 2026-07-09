import json
import logging
from sqlalchemy import create_engine, text
from metahound.json_schema import schema_types_to_string
from metahound.setup import Sources, Files, Fields, TableMetrics, Tables, Scans, SchemaSnapshots, Changes, FileArrivals
from sqlalchemy.orm import sessionmaker
import datetime
import pandas as pd

logger = logging.getLogger(__name__)


def _cli_version() -> str:
    try:
        from importlib.metadata import version
        return version("metahound")
    except Exception:
        return "unknown"


class GenericBackendHandler():
    def __init__(self, connection_uri: str = 'sqlite:///metahound.db'):
        self.connection_uri = connection_uri

        self.connection = self._connect()

    def _connect(self):
        engine = create_engine(self.connection_uri)
        return engine

    def register_scan(self, server: str, last_modified) -> int:
        Session = sessionmaker(bind=self.connection)
        session = Session()

        scan = Scans(server=server, last_modified=last_modified, scan_time=datetime.datetime.utcnow())

        session.add(scan)
        session.commit()
        scan_id = scan.id
        session.close()
        return scan_id


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
                filetype = file['file'].rsplit('.', 1)[-1].lower() if '.' in file['file'] else 'unknown'
                file_entry = Files(name=file['file'], uri=file_uri, filetype=filetype, file_encoding='utf-8')

            if file['properties']:
                for column in file['properties'].keys():
                    column_uri = f"{file_uri}/{column}"
                    column_types = schema_types_to_string(file['properties'][column])
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


    def save_snapshot(self, scan_id: int, source_uri: str, snapshot: dict) -> None:
        """Persist the full schema state of a source as observed by one scan."""
        Session = sessionmaker(bind=self.connection)
        session = Session()

        row = SchemaSnapshots(
            scan_id=scan_id,
            source_uri=source_uri,
            ts=datetime.datetime.utcnow(),
            snapshot=json.dumps(snapshot, sort_keys=True),
        )
        session.add(row)
        session.commit()
        session.close()


    def get_latest_snapshot(self, source_uri: str) -> dict | None:
        """Return the most recent snapshot for a source, or None if never scanned."""
        Session = sessionmaker(bind=self.connection)
        session = Session()

        row = (
            session.query(SchemaSnapshots)
            .filter_by(source_uri=source_uri)
            .order_by(SchemaSnapshots.id.desc())
            .first()
        )
        session.close()

        if row is None:
            return None
        return json.loads(row.snapshot)


    def record_changes(self, scan_id: int, source_uri: str, changes: list) -> None:
        if not changes:
            return

        Session = sessionmaker(bind=self.connection)
        session = Session()

        ts = datetime.datetime.utcnow()
        for change in changes:
            session.add(Changes(
                scan_id=scan_id,
                source_uri=source_uri,
                object_uri=change["object_uri"],
                change_type=change["change_type"],
                severity=change["severity"],
                detail=json.dumps(change.get("detail", {}), sort_keys=True),
                ts=ts,
            ))
        session.commit()
        session.close()


    def record_file_arrivals(self, source_uri: str, arrivals: list) -> None:
        """Persist (fileset, file_name, mtime) arrival observations.

        Re-observing a file updates its mtime rather than duplicating the row.
        The table is created on demand so pre-2.6 backends pick it up without
        re-running `metahound backend`.
        """
        if not arrivals:
            return

        FileArrivals.__table__.create(self.connection, checkfirst=True)

        Session = sessionmaker(bind=self.connection)
        session = Session()

        for fileset, file_name, mtime in arrivals:
            row = (
                session.query(FileArrivals)
                .filter_by(source_uri=source_uri, fileset=fileset, file_name=file_name)
                .first()
            )
            if row is None:
                session.add(FileArrivals(
                    source_uri=source_uri,
                    fileset=fileset,
                    file_name=file_name,
                    mtime=mtime,
                ))
            else:
                row.mtime = mtime
        session.commit()
        session.close()


    def merge_fileset_metrics(self, source_name: str, metrics: list) -> None:
        """Store per-fileset-member metrics as time series in table_metrics.

        metrics: [(fileset, metric_name, value, ts)]. URIs are
        fileset://{source}/{fileset}/{metric} with ts = the member file's
        mtime, so each file becomes one point in its fileset's series and the
        existing outlier pipeline (get_partitions/get_partition) picks the
        series up with no changes. table_id stays NULL — filesets are not
        tables. Points already present (same uri + ts) are skipped.
        """
        if not metrics:
            return

        Session = sessionmaker(bind=self.connection)
        session = Session()

        for fileset, metric_name, value, ts in metrics:
            if value is None:
                continue
            uri = f"fileset://{source_name}/{fileset}/{metric_name}"
            exists = (
                session.query(TableMetrics)
                .filter_by(uri=uri, ts=ts)
                .filter(TableMetrics.metric_name == metric_name)
                .first()
            )
            if exists:
                continue
            session.add(TableMetrics(
                uri=uri,
                ts=ts,
                metric_name=metric_name,
                metric_value=str(value),
            ))
        session.commit()
        session.close()


    def get_file_arrivals(self, source_uri: str) -> dict:
        """Return {fileset: [mtime, ...]} sorted ascending, for one source."""
        FileArrivals.__table__.create(self.connection, checkfirst=True)

        Session = sessionmaker(bind=self.connection)
        session = Session()

        arrivals: dict = {}
        rows = (
            session.query(FileArrivals)
            .filter_by(source_uri=source_uri)
            .order_by(FileArrivals.mtime, FileArrivals.id)
            .all()
        )
        for row in rows:
            arrivals.setdefault(row.fileset, []).append(row.mtime)
        session.close()
        return arrivals


    def get_changes(self, since: datetime.datetime | None = None) -> list:
        """Return change events as dicts.

        With since=None, returns only changes from the most recent scan of each
        source; with a timestamp, returns all changes recorded at or after it.
        """
        Session = sessionmaker(bind=self.connection)
        session = Session()

        query = session.query(Changes).order_by(Changes.ts, Changes.id)
        if since is not None:
            query = query.filter(Changes.ts >= since)
        rows = query.all()

        if since is None:
            # Latest scan per source comes from snapshots (every scan writes
            # one), so a clean scan correctly yields no changes here.
            latest_scan = {}
            for snap in session.query(SchemaSnapshots).all():
                if snap.scan_id is not None:
                    latest_scan[snap.source_uri] = max(
                        latest_scan.get(snap.source_uri, 0), snap.scan_id
                    )
            rows = [r for r in rows if r.scan_id == latest_scan.get(r.source_uri)]

        changes = [
            {
                "ts": row.ts,
                "scan_id": row.scan_id,
                "source_uri": row.source_uri,
                "object_uri": row.object_uri,
                "change_type": row.change_type,
                "severity": row.severity,
                "detail": json.loads(row.detail) if row.detail else {},
            }
            for row in rows
        ]
        session.close()
        return changes


    def get_partition(self, partition: str) -> pd.DataFrame:
        # Executed via SQLAlchemy rather than pandas.read_sql_query: pandas 2.x
        # rejects SQLAlchemy 1.4 connectables, which this package still pins.
        query = text(
            "SELECT ts as ds, CAST(metric_value AS FLOAT) as y FROM table_metrics"
            " WHERE uri = :uri ORDER BY ds LIMIT 1000"
        )
        with self.connection.connect() as conn:
            rows = conn.execute(query, {"uri": partition}).fetchall()
        return pd.DataFrame(rows, columns=["ds", "y"])

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

        changes_data = [
            {
                "ts": row.ts.isoformat() if row.ts else None,
                "source_uri": row.source_uri,
                "object_uri": row.object_uri,
                "change_type": row.change_type,
                "severity": row.severity,
                "detail": json.loads(row.detail) if row.detail else {},
            }
            for row in session.query(Changes).order_by(Changes.ts, Changes.id).all()
        ]

        session.close()
        return {
            "sources": sources_data,
            "changes": changes_data,
            "cli_version": _cli_version(),
        }


    def get_partitions(self) -> list:
        query = text("SELECT DISTINCT uri FROM table_metrics")
        with self.connection.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [row[0] for row in rows]


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
