from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from metadog.db_scanners import GenericDBScanner


class MSSQLScanner(GenericDBScanner):
    """SQLAlchemy-based scanner for Microsoft SQL Server."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        database: str,
        port: int = 1433,
        driver: str = "pymssql",
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.database = database
        self.port = port
        self.driver = driver

        self.engine = self._connect()

    def _connect(self):
        url = URL.create(
            drivername=f"mssql+{self.driver}",
            host=self.host,
            username=self.username,
            password=self.password,
            port=self.port,
            database=self.database,
        )
        return create_engine(url)

    @property
    def base_uri(self):
        return f"mssql+{self.driver}://{self.host}/{self.database}"
