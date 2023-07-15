# import sqlalchemy
# from sqlalchemy import create_engine
# from sqlalchemy.engine import URL
# from snowflake.sqlalchemy import URL as sfURL
# from .analyze import analyze_table
# from sqlalchemy.orm import sessionmaker
# from .setup import Sources, Files, Fields, TableMetrics, Tables, ColumnMetrics
# import datetime
# import os

# def get_db_uri(db_type: str, **kwargs) -> URL | str:
#     """
#     Returns a database URI for sqlalchemy to connect to
#     """
#     if db_type == 'postgres':
#         kwargs["port"] = kwargs.get('port') or 5432
#         kwargs["drivername"] = kwargs.get('drivername') or 'postgresql'
#         pgurl = URL.create(**kwargs)

#         return pgurl

#     elif db_type == 'mysql':
#         kwargs["port"] = kwargs.get('port') or 5432
#         kwargs["drivername"] = kwargs.get('drivername') or 'mysql+pymysql'
#         mysqlurl = URL.create(**kwargs)

#         return mysqlurl

#     elif db_type == 'snowflake':
#         sfurl = sfURL(**kwargs)
#         return sfurl

#     else:
#         raise NotImplementedError("Database type not implemented")


# def get_table_schema(schema_name, table_name: str, engine) -> str:
#     inspector = sqlalchemy.inspect(engine)
#     tbl_schema = inspector.get_columns(schema=schema_name, table_name=table_name)
#     return tbl_schema


# def get_tables_in_schema(schema: str, engine) -> list:
#     inspector = sqlalchemy.inspect(engine)
#     tables = inspector.get_table_names(schema=schema)
#     return tables


# def get_schemas_in_db(engine) -> list:
#     inspector = sqlalchemy.inspect(engine)
#     schemas = inspector.get_schema_names()
#     return schemas


# def convert_schema_to_singer(schema):
#     """
#     Convert a schema from sqlalchemy to a singer schema.
#     """
#     singer_schema = {
#         "type": ["object"],
#         "properties": {},
#         "additionalProperties": False,
#     }

#     for column in schema:
#         singer_schema["properties"][column["name"]] = {
#             "type": str(column["type"]),
#         }

#     return singer_schema


# def convert_schema_to_openlineage(schema, namespace, name):
#     """
#     Convert a schema from sqlalchemy to an openlineage schema.
#     """
#     openlineage_schema = {
#         "type": "object",
#         "properties": {},
#         "additionalProperties": False,
#     }

#     for column in schema:
#         openlineage_schema["properties"][column["name"]] = {
#             "type": str(column["type"].as_generic()),
#         }

#     return openlineage_schema


# def profile_db(db_flavor, db_name, connection_info, do_scan) -> tuple:
#     """
#     Profile a database and return a list of singer schemas.
#     """
#     connection_info["database"] = db_name
#     db_uri = get_db_uri(db_flavor, **connection_info)
#     engine = create_engine(db_uri)

#     schemas = get_schemas_in_db(engine)
#     full_scan = {"database": db_name, "schemas": {}}
#     all_stats = {"database": db_name, "stats": []}
#     for schema in schemas:
#         tables = get_tables_in_schema(schema, engine)
#         tbl_schemas = []
#         for table in tables:
#             print(f"Getting {table} from {schema}")
#             tbl_schema = get_table_schema(schema, table, engine)
#             gotten_table_schema = convert_schema_to_singer(tbl_schema)
#             gotten_table_schema["name"] = table
#             tbl_schemas.append(gotten_table_schema)
#             if do_scan:
#                 stats = analyze_table(tbl_name=table, schema=schema, engine=engine)
#                 all_stats["stats"].append({"table": table, "schema": schema, "stats": stats})

#         full_scan["schemas"][schema] = tbl_schemas

#         merge_database_crawl(db_name, full_scan)
#         merge_database_stats(db_name, all_stats)

#     return full_scan, all_stats


# def merge_database_stats(domain, db_json):
    
#     ts = datetime.datetime.utcnow()

#     connect_string = os.getenv("METADOG_BACKEND_URI") or 'sqlite:///metadog.db'
#     engine = create_engine(connect_string)

#     Session = sessionmaker(bind=engine)
#     session = Session()
#     source_uri = f"snowflake://{domain}"

#     source = session.query(Sources).filter_by(uri=source_uri).first()

#     if not source:
#         print("creating source")
#         source = Sources(name="ax", type="database", uri=source_uri)

#     session.merge(source)

#     for stat in db_json['stats']:
#         table_uri = f"{source_uri}/{db_json['database']}/{stat['schema']}/{stat['table']}"
#         table = session.query(Tables).filter_by(uri=table_uri).first()
#         if not table:
#             table = Tables(name=stat["table"], uri = table_uri, db_name=db_json['database'], schema_name=stat['schema'])
#         else:
#             table.db_name=db_json['database'] 
#             table.schema_name=stat['schema']
#         source.tables.append(table)


#         for metric in stat['stats'][0].keys():

#             tbl_metric = TableMetrics(
#                 metric_name=metric, 
#                 metric_value=float(stat['stats'][0][metric]), 
#                 uri = f"{table_uri}/{metric}",
#                 ts = ts
#                 )
#             table.table_metrics.append(tbl_metric)

#     session.merge(source)
#     session.commit()
#     session.close()


# def merge_database_crawl(domain, db_json):
    
#     connect_string = os.getenv("METADOG_BACKEND_URI") or 'sqlite:///metadog.db'
#     engine = create_engine(connect_string)

#     Session = sessionmaker(bind=engine)
#     session = Session()
#     source = session.query(Sources).filter_by(uri=f"snowflake://{domain}").first()
    
#     if not source:
#         source = Sources(name="ax", type="database", uri=f"snowflake://{domain}")


#     for schema_name in db_json['schemas'].keys():
        
#         schema = db_json['schemas'][schema_name]

#         for table_element in db_json['schemas'][schema_name]:
#             table_uri = f"snowflake://{domain}/{db_json['database']}/{schema_name}/{table_element['name']}"
#             table = session.query(Tables).filter_by(uri=table_uri).first()
#             if not table:
#                 table = Tables(name=table_element["name"], uri = table_uri, db_name=db_json['database'], schema_name=schema_name)
#             else:
#                 table.db_name=db_json['database'] 
#                 table.schema_name=schema_name
#             source.tables.append(table)

#             for column_name in table_element['properties'].keys():
#                 column_uri = f"{table_uri}/{column_name}"
#                 column = session.query(Fields).filter_by(uri=column_uri).first()
#                 if not column:
#                     column = Fields(name=column_name, type=table_element['properties'][column_name]['type'], uri = column_uri)
#                 else:
#                     column.type=table_element['properties'][column_name]['type']
#                 table.fields.append(column)


#     session.merge(source)
#     # Commit the session to write the data to the database
#     session.commit()
#     session.close()


