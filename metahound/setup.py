from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.orm import declarative_base
import os

Base = declarative_base()

class Sources(Base):
    __tablename__ = 'sources'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    type = Column(String)
    uri = Column(String, unique=True)
    files = relationship("Files", back_populates="source")
    tables = relationship("Tables", back_populates="source")
    # databases = relationship("Databases", back_populates="source")

class Files(Base):
    __tablename__ = 'files'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    uri = Column(String, unique=True)
    filetype = Column(String)
    file_encoding = Column(String)
    source_id = Column(String, ForeignKey('sources.uri'))

    source = relationship("Sources", back_populates="files")
    fields = relationship("Fields", back_populates="file")

# class Databases(Base):
#     __tablename__ = 'databases'

#     id = Column(Integer, primary_key=True)
#     name = Column(String)
#     type = Column(String)
#     uri = Column(String)
#     source_id = Column(Integer, ForeignKey('sources.id'))

#     source = relationship("Sources", back_populates="databases")
#     tables = relationship("Tables", back_populates="database")


class Tables(Base):
    __tablename__ = 'tables'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    uri = Column(String, unique=True)
    db_name = Column(String)
    schema_name = Column(String)

    source_id = Column(String, ForeignKey('sources.uri'))
    source = relationship("Sources", back_populates="tables")
    # database_id = Column(Integer, ForeignKey('databases.id'))
    # database = relationship("Databases", back_populates="tables")
    fields = relationship("Fields", back_populates="table")
    table_metrics = relationship("TableMetrics", back_populates="table")


class Fields(Base):
    __tablename__ = 'fields'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    type = Column(String)
    uri = Column(String, unique=True)

    file_id = Column(String, ForeignKey('files.uri'))
    file = relationship("Files", back_populates="fields")

    table_id = Column(String, ForeignKey('tables.uri'))
    table = relationship("Tables", back_populates="fields")

    column_metrics = relationship("ColumnMetrics", back_populates="field")


class TableMetrics(Base):
    __tablename__ = 'table_metrics'
    id = Column(Integer, primary_key=True)
    uri = Column(String)
    ts = Column(DateTime)
    table_id = Column(String, ForeignKey('tables.uri'))
    table = relationship("Tables", back_populates="table_metrics")
    metric_name = Column(String)
    metric_value = Column(String)


class ColumnMetrics(Base):
    __tablename__ = 'column_metrics'
    id = Column(Integer, primary_key=True)
    uri = Column(String)
    ts = Column(DateTime)
    field_id = Column(String, ForeignKey('fields.uri'))
    metric_name = Column(String)
    metric_value = Column(String)

    field = relationship("Fields", back_populates="column_metrics")


class Scans(Base):
    __tablename__ = 'scans'
    id = Column(Integer, primary_key=True)
    server = Column(String)
    scan_time = Column(DateTime)
    last_modified = Column(DateTime)


def run_model_ddls():
    backend_uri = os.getenv("METAHOUND_BACKEND_URI")

    if backend_uri is None:
        raise ValueError("METAHOUND_BACKEND_URI environment variable is not set")

    # Create the tables if they don't already exist
    engine = create_engine(backend_uri)
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    os.environ["METAHOUND_BACKEND_URI"] = "sqlite:///metahound.db"
    run_model_ddls()