import gzip
import io
import json
from unittest.mock import MagicMock

import pytest

from metahound.cli_functions import handle_file
from metahound.file_handlers.csv_handler import CSVHandler
from metahound.file_handlers.encoding import detect_encoding
from metahound.file_handlers.json_handler import JSONHandler

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def _fs(content: bytes):
    filesystem = MagicMock()
    filesystem.get_file.return_value = io.BytesIO(content)
    return filesystem

CSV_CONTENT = b"id,name\n1,alpha\n2,beta\n"


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------

class TestEncodingDetection:
    def test_utf8_bom(self):
        assert detect_encoding(b"\xef\xbb\xbfid,name\n") == "utf-8-sig"

    def test_plain_ascii_defaults_utf8(self):
        assert detect_encoding(b"id,name\n1,alpha\n") in ("utf-8", "ascii")

    def test_latin1_csv_parses(self):
        # A utf-8 decode of this content would raise UnicodeDecodeError;
        # enough rows for csv.Sniffer to recognise the header.
        rows = "\n".join(f"{i},Sæbø{i}" for i in range(1, 8))
        content = f"id,city\n{rows}\n".encode("latin-1")
        handler = CSVHandler(io.BytesIO(content), "cities.csv", get_schema=True)
        assert handler.encoding == "cp1252"
        meta = handler.get_file_metadata()
        assert set(meta["properties"]) == {"id", "city"}

    def test_encoding_reported_in_metadata(self):
        meta = CSVHandler(io.BytesIO(CSV_CONTENT), "f.csv", get_schema=True).get_file_metadata()
        assert "file_encoding" in meta


# ---------------------------------------------------------------------------
# Compressed files
# ---------------------------------------------------------------------------

class TestGzip:
    def test_csv_gz_dispatches_to_csv_handler(self):
        meta = handle_file("orders.csv.gz", _fs(gzip.compress(CSV_CONTENT)), True)
        assert set(meta["properties"]) == {"id", "name"}

    def test_jsonl_gz(self):
        content = b'{"id": 1}\n{"id": 2}\n'
        meta = handle_file("events.jsonl.gz", _fs(gzip.compress(content)), True)
        assert "id" in meta["properties"]

    def test_unknown_gz_stays_unhandled(self):
        meta = handle_file("blob.bin.gz", _fs(gzip.compress(b"junk")), True)
        assert meta == {"file": "blob.bin.gz", "properties": {}}


# ---------------------------------------------------------------------------
# Plain JSON
# ---------------------------------------------------------------------------

class TestJSONHandler:
    def test_array_of_objects(self):
        content = json.dumps([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]).encode()
        meta = JSONHandler(io.BytesIO(content), "data.json", get_schema=True).get_file_metadata()
        assert set(meta["properties"]) == {"id", "name"}
        assert meta["num_rows"] == 2

    def test_single_object(self):
        meta = JSONHandler(io.BytesIO(b'{"id": 1}'), "one.json", get_schema=True).get_file_metadata()
        assert "id" in meta["properties"]
        assert meta["num_rows"] == 1

    def test_invalid_json_degrades(self):
        meta = JSONHandler(io.BytesIO(b"not json"), "bad.json", get_schema=True).get_file_metadata()
        assert meta["properties"] == {}

    def test_dispatch_via_handle_file(self):
        content = json.dumps([{"id": 1}]).encode()
        meta = handle_file("data.json", _fs(content), True)
        assert "id" in meta["properties"]


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl not installed")
class TestExcelHandler:
    def _xlsx(self, rows):
        import openpyxl

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        return buffer.read()

    def test_schema_and_row_count(self):
        content = self._xlsx([("id", "name"), (1, "alpha"), (2, "beta")])
        meta = handle_file("report.xlsx", _fs(content), True)
        assert set(meta["properties"]) == {"id", "name"}
        assert meta["num_rows"] == 2

    def test_header_only_file(self):
        content = self._xlsx([("id", "name")])
        meta = handle_file("empty.xlsx", _fs(content), True)
        assert set(meta["properties"]) == {"id", "name"}
        assert meta["num_rows"] == 0
