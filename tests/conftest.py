import datetime
import pytest
from sqlalchemy.orm import sessionmaker

from metahound.backend_handlers import GenericBackendHandler
from metahound.setup import Base, Fields, Files, Sources, TableMetrics, Tables


@pytest.fixture
def in_memory_backend():
    backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
    Base.metadata.create_all(backend.connection)
    return backend


@pytest.fixture
def backend_with_data(in_memory_backend):
    Session = sessionmaker(bind=in_memory_backend.connection)
    session = Session()

    source = Sources(name="test_db", type="database", uri="db://test_db")
    table = Tables(
        name="test_table",
        uri="db://test_db/mydb/myschema/test_table",
        db_name="mydb",
        schema_name="myschema",
    )
    field = Fields(
        name="id",
        type="integer",
        uri="db://test_db/mydb/myschema/test_table/id",
    )
    table.fields.append(field)

    for i in range(5):
        metric = TableMetrics(
            metric_name="row_count",
            metric_value=str(100 + i * 10),
            uri="db://test_db/mydb/myschema/test_table/row_count",
            ts=datetime.datetime(2024, 1, i + 1),
        )
        table.table_metrics.append(metric)

    source.tables.append(table)
    session.merge(source)
    session.commit()
    session.close()

    return in_memory_backend
