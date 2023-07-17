from sqlalchemy import create_engine, inspect
import fsspec
import csv
from metadog.json_schema import sample_file, generate_schema
from metadog.setup import Sources, Files, Fields, TableMetrics, Tables, ColumnMetrics, Scans
from sqlalchemy.orm import sessionmaker
import os
import datetime
import pandas as pd

class GenericBackendHandler():
    def __init__(self, connection_uri = 'sqlite:///metadog.db'):
        self.connection_uri = connection_uri

        self.connection = self._connect()

    def _connect(self):
        engine = create_engine(self.connection_uri)
        return engine

    def register_scan(self, server, last_modified):
        engine = self._connect()
        Session = sessionmaker(bind=engine)
        session = Session()


        scan = Scans(server=server, last_modified=last_modified, scan_time=datetime.datetime.utcnow() )
        
        session.add(scan)
        session.commit()
        session.close()


    def get_last_modified(self, server):
        engine = self._connect()
        Session = sessionmaker(bind=engine)
        session = Session()

        last_modified = session.query(Scans).filter_by(server=server).order_by(Scans.scan_time.desc()).first()

        session.close()

        if last_modified is None:
            return datetime.datetime(1970, 1, 1, 0, 0, 0, 0)

        return last_modified.last_modified


    def merge_file_crawl(self, domain, protocol, file_list):
        
        engine = self._connect()
        Session = sessionmaker(bind=engine)
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
                    column_types = '/'.join([ f_type for f_type in file['properties'][column]['type'] if f_type!='null'])
                    column_entry = session.query(Fields).filter_by(uri=column_uri).first()
                    if not column_entry:
                        column_entry = Fields(name=column, type=column_types, uri=column_uri)

                    file_entry.fields.append(column_entry)

            source.files.append(file_entry)

        session.merge(source)
        # Commit the session to write the data to the database
        session.commit()
        session.close()


    def merge_database_crawl(self, domain, db_json):
        
        Session = sessionmaker(bind=self.connection)
        session = Session()
        source_uri = f"db://{domain}"

        source = session.query(Sources).filter_by(uri=source_uri).first() # TODO: get the protocol from somewhere

        if not source:
            source = Sources(name=domain, type="database", uri=source_uri) # TODO: get the protocol from somewhere


        for schema_name in db_json['schemas'].keys():

            for table_element in db_json['schemas'][schema_name]:
                table_uri = f"db://{domain}/{db_json['database']}/{schema_name}/{table_element['name']}"
                table = session.query(Tables).filter_by(uri=table_uri).first()
                if not table:
                    table = Tables(name=table_element["name"], uri = table_uri, db_name=db_json['database'], schema_name=schema_name)
                else:
                    table.db_name=db_json['database'] 
                    table.schema_name=schema_name
                source.tables.append(table)

                for column_name in table_element['properties'].keys():
                    column_uri = f"{table_uri}/{column_name}"
                    column = session.query(Fields).filter_by(uri=column_uri).first()
                    if not column:
                        column = Fields(name=column_name, type=table_element['properties'][column_name]['type'], uri = column_uri)
                    else:
                        column.type=table_element['properties'][column_name]['type']
                    table.fields.append(column)


        session.merge(source)
        # Commit the session to write the data to the database
        session.commit()
        session.close()


    def merge_database_stats(self, domain, db_json):
        
        ts = datetime.datetime.utcnow()

        connect_string = os.getenv("METADOG_BACKEND_URI") or 'sqlite:///metadog.db'
        engine = create_engine(connect_string)

        Session = sessionmaker(bind=engine)
        session = Session()
        source_uri = f"db://{domain}"

        source = session.query(Sources).filter_by(uri=source_uri).first()

        if not source:
            print("creating source")
            source = Sources(name=domain, type="database", uri=source_uri)
        # session.merge(source)


        for stat in db_json['stats']:
            table_uri = f"{source_uri}/{db_json['database']}/{stat['schema']}/{stat['table']}"
            table = session.query(Tables).filter_by(uri=table_uri).first()
            if not table:
                table = Tables(name=stat["table"], uri = table_uri, db_name=db_json['database'], schema_name=stat['schema'])
            else:
                table.db_name=db_json['database'] 
                table.schema_name=stat['schema']
            source.tables.append(table)

            def coerce_float(x):
                try:
                    return float(x)
                except:
                    return None

            for metric in stat['stats'][0].keys():
                float_value = coerce_float(stat['stats'][0][metric])
                tbl_metric = TableMetrics(
                    metric_name=metric, 
                    metric_value=float_value, 
                    uri = f"{table_uri}/{metric}",
                    ts = ts
                    )
                table.table_metrics.append(tbl_metric)

        session.merge(source)
        session.commit()
        session.close()


    def get_partition(self, partition):
        df = pd.read_sql_query("""
        SELECT ts as ds, CAST(metric_value as FLOAT) as y FROM table_metrics WHERE uri = '{}'
        ORDER BY ds
        LIMIT 1000
        """.format(partition), self.connection)

        return df


    def get_partitions(self):
        partitions = pd.read_sql_query("SELECT distinct uri FROM table_metrics", self.connection)
        return list(partitions['uri'])
