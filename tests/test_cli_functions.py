import datetime
import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy.orm import sessionmaker

from metahound.backend_handlers import GenericBackendHandler
from metahound.setup import Base, Sources, Tables, Files, Scans
from metahound.cli_functions import _scan_filesystem_source, handle_file, status_fn


# ---------------------------------------------------------------------------
# _scan_filesystem_source tests
# ---------------------------------------------------------------------------

class TestScanFilesystemSource:
    def _make_backend(self):
        backend = GenericBackendHandler(connection_uri="sqlite:///:memory:")
        Base.metadata.create_all(backend.connection)
        return backend

    def test_only_new_files_processed(self):
        backend = self._make_backend()
        highwater = datetime.datetime(2024, 1, 5)

        old_file = {"name": "old.csv", "mtime": datetime.datetime(2024, 1, 1)}
        new_file = {"name": "new.csv", "mtime": datetime.datetime(2024, 1, 10)}

        filesystem = MagicMock()
        filesystem.get_files.return_value = [old_file, new_file]
        filesystem.get_last_modified.return_value = datetime.datetime(2024, 1, 10)
        filesystem.get_file.return_value = b""

        with patch("metahound.cli_functions.handle_file") as mock_handle:
            mock_handle.return_value = {"file": "new.csv", "properties": {}}
            with patch.object(backend, "get_last_modified", return_value=highwater):
                _scan_filesystem_source("my_source", "sftp", filesystem, backend, False)

        # handle_file should only be called for the new file
        mock_handle.assert_called_once_with("new.csv", filesystem, False)

    def test_merge_and_register_called(self):
        backend = self._make_backend()

        filesystem = MagicMock()
        filesystem.get_files.return_value = [
            {"name": "a.csv", "mtime": datetime.datetime(2024, 2, 1)}
        ]
        filesystem.get_last_modified.return_value = datetime.datetime(2024, 2, 1)

        with patch("metahound.cli_functions.handle_file") as mock_handle:
            mock_handle.return_value = {"file": "a.csv", "properties": {}}
            with patch.object(backend, "get_last_modified", return_value=datetime.datetime(1970, 1, 1)):
                with patch.object(backend, "merge_file_crawl") as mock_merge:
                    with patch.object(backend, "register_scan") as mock_register:
                        _scan_filesystem_source("my_source", "s3", filesystem, backend, False)

        mock_merge.assert_called_once_with(
            domain="my_source", protocol="s3",
            file_list=[{"file": "a.csv", "properties": {}}]
        )
        mock_register.assert_called_once_with(
            server="my_source",
            last_modified=datetime.datetime(2024, 2, 1)
        )

    def test_no_files_above_highwater(self):
        backend = self._make_backend()
        highwater = datetime.datetime(2024, 6, 1)

        filesystem = MagicMock()
        filesystem.get_files.return_value = [
            {"name": "old.csv", "mtime": datetime.datetime(2024, 1, 1)}
        ]
        filesystem.get_last_modified.return_value = datetime.datetime(2024, 1, 1)

        with patch("metahound.cli_functions.handle_file") as mock_handle:
            with patch.object(backend, "get_last_modified", return_value=highwater):
                with patch.object(backend, "merge_file_crawl") as mock_merge:
                    _scan_filesystem_source("my_source", "sftp", filesystem, backend, False)

        mock_handle.assert_not_called()
        mock_merge.assert_called_once_with(domain="my_source", protocol="sftp", file_list=[])


# ---------------------------------------------------------------------------
# status_fn tests
# ---------------------------------------------------------------------------

class TestStatusFn:
    def test_status_output_contains_source(self, backend_with_data, capsys, monkeypatch):
        monkeypatch.setattr(
            "metahound.cli_functions._get_backend",
            lambda: backend_with_data
        )
        status_fn()
        captured = capsys.readouterr()
        assert "test_db" in captured.out

    def test_status_output_table_count(self, backend_with_data, capsys, monkeypatch):
        monkeypatch.setattr(
            "metahound.cli_functions._get_backend",
            lambda: backend_with_data
        )
        status_fn()
        captured = capsys.readouterr()
        # The backend_with_data fixture has 1 table and 0 files for test_db
        assert "1" in captured.out

    def test_status_no_sources(self, in_memory_backend, capsys, monkeypatch):
        monkeypatch.setattr(
            "metahound.cli_functions._get_backend",
            lambda: in_memory_backend
        )
        status_fn()
        captured = capsys.readouterr()
        assert "Sources (0)" in captured.out
        assert "none" in captured.out
