import logging
from sqlalchemy import create_engine, MetaData, Table, select, func, Numeric, Integer, String, distinct, inspect, tablesample
from sqlalchemy.engine import URL
from metahound.json_schema import convert_schema_to_singer

logger = logging.getLogger(__name__)


def _scale_sampled_counts(result_dict: list, sample_percent: float | None) -> list:
    """Scale count metrics from a sample back to table size.

    Keeps the row_count/null_count time series comparable to full scans.
    Unique counts are not scalable and stay as observed on the sample;
    min/avg/max need no scaling.
    """
    if not sample_percent:
        return result_dict

    factor = 100.0 / sample_percent
    for row in result_dict:
        for key, value in row.items():
            if value is not None and (key == "row_count" or key.endswith("__null_count")):
                row[key] = round(value * factor)
    return result_dict


class GenericDBScanner():

    def __init__(self, host, username, password, drivername, port, database, options={}) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.drivername = drivername
        self.port = port
        self.database = database
        self.options = options

        self.engine = self._connect()


    def _connect(self):
        url = URL.create(
            drivername=self.drivername,
            host=self.host,
            username=self.username,
            password=self.password,
            port=self.port,
            database=self.database,
            query=self.options
        )

        engine = create_engine(url)

        return engine


    @property
    def base_uri(self):
        return f"{self.drivername}://{self.host}"


    def _build_stats_query(self, table, heavy: bool, sample_percent: float | None):
        """One aggregate pass over the table (or a sample of it).

        Cheap stats — row count, per-column null counts, numeric min/avg/max —
        are always included. COUNT(DISTINCT) on string columns is the query
        that hurts on wide production tables, so it only runs with heavy=True.
        """
        stats_target = table
        if sample_percent:
            stats_target = tablesample(table, sample_percent)

        def col(column):
            return stats_target.columns[column.name]

        numeric_columns = [c for c in table.columns if isinstance(c.type, (Numeric, Integer))]
        char_columns = [c for c in table.columns if isinstance(c.type, String)]

        selects = []
        for column in numeric_columns:
            selects += [
                func.min(col(column)).label(f"{column.name}__min"),
                func.avg(col(column)).label(f"{column.name}__avg"),
                func.max(col(column)).label(f"{column.name}__max"),
                func.count(col(column)).label(f"{column.name}__null_count"),
            ]

        for column in char_columns:
            if heavy:
                selects.append(
                    func.count(distinct(col(column))).label(f"{column.name}__unique_count")
                )
            selects.append(func.count(col(column)).label(f"{column.name}__null_count"))

        selects.append(func.count().label("row_count"))
        # star-args form works on both SQLAlchemy 1.4 and 2.0
        return select(*selects).select_from(stats_target)


    def analyze_table(
        self,
        tbl_name: str,
        schema: str,
        heavy: bool = False,
        sample_percent: float | None = None,
    ) -> list:

        metadata = MetaData(schema=schema)
        table = Table(tbl_name, metadata, autoload_with=self.engine)

        stmt = self._build_stats_query(table, heavy, sample_percent)
        with self.engine.connect() as conn:
            result = conn.execute(stmt)
            result_dict = [dict(row._mapping) for row in result]

        return _scale_sampled_counts(result_dict, sample_percent)


    def get_table_schema(self, schema_name: str, table_name: str) -> list:
        inspector = inspect(self.engine)
        tbl_schema = inspector.get_columns(schema=schema_name, table_name=table_name)
        return tbl_schema


    def get_tables_in_schema(self, schema: str) -> list:
        inspector = inspect(self.engine)
        tables = inspector.get_table_names(schema=schema)
        return tables


    def get_schemas_in_db(self) -> list:
        inspector = inspect(self.engine)
        schemas = inspector.get_schema_names()
        return schemas


    def profile_db(self, db_name: str, do_scan: bool, stats_config: dict | None = None) -> tuple:
        """
        Profile a database and return a list of singer schemas.
        """
        stats_config = stats_config or {}

        schemas = self.get_schemas_in_db()
        full_scan = {"database": db_name, "schemas": {}}
        all_stats = {"database": db_name, "stats": []}
        for schema in schemas:
            tables = self.get_tables_in_schema(schema)
            tbl_schemas = []
            for table in tables:
                logger.debug(f"Getting {table} from {schema}")
                tbl_schema = self.get_table_schema(schema, table)
                gotten_table_schema = convert_schema_to_singer(tbl_schema)
                gotten_table_schema["name"] = table
                tbl_schemas.append(gotten_table_schema)
                if do_scan:
                    stats = self.analyze_table(
                        tbl_name=table,
                        schema=schema,
                        heavy=stats_config.get("heavy", False),
                        sample_percent=stats_config.get("sample_percent"),
                    )
                    all_stats["stats"].append({"table": table, "schema": schema, "stats": stats})

            full_scan["schemas"][schema] = tbl_schemas

        return full_scan, all_stats
