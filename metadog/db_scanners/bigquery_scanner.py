from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from metadog.db_scanners import GenericDBScanner


class BigQueryScanner(GenericDBScanner):
    """SQLAlchemy-based scanner for Google BigQuery."""

    def __init__(self, project: str, dataset: str, credentials_path: str | None = None) -> None:
        self.project = project
        self.dataset = dataset
        self.credentials_path = credentials_path

        self.engine = self._connect()

    def _connect(self):
        url = URL.create(
            drivername="bigquery",
            host=self.project,
            database=self.dataset,
        )
        kwargs = {}
        if self.credentials_path:
            kwargs["credentials_path"] = self.credentials_path
        return create_engine(url, **kwargs)

    @property
    def base_uri(self):
        return f"bigquery://{self.project}"
