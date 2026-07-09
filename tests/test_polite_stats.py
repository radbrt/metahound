import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, Numeric, String, Table

from metahound.db_scanners import GenericDBScanner, _scale_sampled_counts


def _sqlite_scanner():
    return GenericDBScanner(
        host=None, username=None, password=None,
        drivername="sqlite", port=None, database=":memory:",
    )


def _orders_table(metadata):
    return Table(
        "orders", metadata,
        Column("id", Integer),
        Column("total", Numeric),
        Column("customer", String),
        Column("created_at", DateTime),
    )


class TestBuildStatsQuery:
    def _sql(self, heavy=False, sample_percent=None):
        scanner = _sqlite_scanner()
        table = _orders_table(MetaData())
        stmt = scanner._build_stats_query(table, heavy=heavy, sample_percent=sample_percent)
        return str(stmt)

    def test_default_skips_count_distinct(self):
        sql = self._sql(heavy=False)
        assert "distinct" not in sql.lower()
        assert "row_count" in sql
        assert "customer__null_count" in sql
        assert "total__min" in sql and "total__avg" in sql and "total__max" in sql

    def test_heavy_adds_unique_counts(self):
        sql = self._sql(heavy=True)
        assert "count(DISTINCT" in sql.replace("distinct", "DISTINCT")
        assert "customer__unique_count" in sql

    def test_sample_percent_renders_tablesample(self):
        sql = self._sql(sample_percent=5.0)
        assert "TABLESAMPLE" in sql.upper()


class TestAnalyzeExecution:
    def _scanner_with_data(self):
        scanner = _sqlite_scanner()
        metadata = MetaData()
        table = _orders_table(metadata)
        metadata.create_all(scanner.engine)
        with scanner.engine.begin() as conn:
            for i in range(6):
                conn.execute(table.insert().values(
                    id=i, total=i * 10.0,
                    customer=f"cust_{i % 3}",  # 3 distinct values
                    created_at=datetime.datetime(2026, 7, 1),
                ))
        return scanner

    def test_cheap_stats_by_default(self):
        scanner = self._scanner_with_data()
        rows = scanner.analyze_table("orders", schema=None)
        stats = rows[0]
        assert stats["row_count"] == 6
        assert stats["id__min"] == 0 and stats["id__max"] == 5
        assert "customer__unique_count" not in stats

    def test_heavy_stats_opt_in(self):
        scanner = self._scanner_with_data()
        stats = scanner.analyze_table("orders", schema=None, heavy=True)[0]
        assert stats["customer__unique_count"] == 3


class TestScaleSampledCounts:
    def test_counts_scaled_uniques_untouched(self):
        rows = [{
            "row_count": 500,
            "customer__null_count": 50,
            "customer__unique_count": 42,
            "total__avg": 12.5,
            "total__min": None,
        }]
        scaled = _scale_sampled_counts(rows, sample_percent=10.0)[0]
        assert scaled["row_count"] == 5000
        assert scaled["customer__null_count"] == 500
        assert scaled["customer__unique_count"] == 42
        assert scaled["total__avg"] == 12.5
        assert scaled["total__min"] is None

    def test_no_sampling_is_identity(self):
        rows = [{"row_count": 5}]
        assert _scale_sampled_counts(rows, None)[0]["row_count"] == 5
