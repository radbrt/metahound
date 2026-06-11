from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from metahound.db_scanners import GenericDBScanner


class OracleScanner(GenericDBScanner):
    """SQLAlchemy-based scanner for Oracle Database."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        service_name: str,
        port: int = 1521,
        driver: str = "oracledb",
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.service_name = service_name
        self.port = port
        self.driver = driver

        self.engine = self._connect()

    def _connect(self):
        url = URL.create(
            drivername=f"oracle+{self.driver}",
            host=self.host,
            username=self.username,
            password=self.password,
            port=self.port,
            query={"service_name": self.service_name},
        )
        return create_engine(url)

    @property
    def base_uri(self):
        return f"oracle+{self.driver}://{self.host}/{self.service_name}"
