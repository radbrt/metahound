from metahound.db_scanners import GenericDBScanner
from snowflake.sqlalchemy import URL
from sqlalchemy import create_engine

class SnowflakeScanner(GenericDBScanner):

    def __init__(self, account, user, password, role, warehouse, database, **kwargs) -> None:
        self.account = account
        self.user = user
        self.password = password
        self.database = database
        self.role = role
        self.warehouse = warehouse

        self.engine = self._connect()


    def _connect(self):
        url = URL(
            account=self.account,
            user=self.user,
            password=self.password,
            database=self.database,
            role=self.role,
            warehouse=self.warehouse,
        )

        engine = create_engine(url)

        return engine

    @property
    def base_uri(self):
        return f"snowflake://{self.account}/{self.database}"
