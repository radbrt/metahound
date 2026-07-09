from unittest.mock import patch

import pytest

from metahound.cli_functions import _redact_secrets
from metahound.connection_handlers.sftp_connection import SFTPFileSystem


class TestSFTPAuth:
    def test_key_auth_passes_key_filename_and_port(self):
        with patch("fsspec.filesystem") as fs:
            SFTPFileSystem(
                host="sftp.example.com", username="hound", port=2222,
                key_path="~/.ssh/metahound_ed25519", key_passphrase="s3cret",
            )
        kwargs = fs.call_args.kwargs
        assert kwargs["key_filename"].endswith(".ssh/metahound_ed25519")
        assert not kwargs["key_filename"].startswith("~")  # expanded
        assert kwargs["passphrase"] == "s3cret"
        assert kwargs["port"] == 2222
        assert "password" not in kwargs

    def test_password_auth_still_works(self):
        with patch("fsspec.filesystem") as fs:
            SFTPFileSystem(host="h", username="u", password="pw")
        kwargs = fs.call_args.kwargs
        assert kwargs["password"] == "pw"
        assert kwargs["port"] == 22  # previously accepted but never passed
        assert "key_filename" not in kwargs

    def test_key_wins_over_password(self):
        with patch("fsspec.filesystem") as fs:
            SFTPFileSystem(host="h", username="u", password="pw", key_path="/k")
        assert "password" not in fs.call_args.kwargs

    def test_no_credentials_raises(self):
        with pytest.raises(ValueError, match="key_path"):
            SFTPFileSystem(host="h", username="u")


class TestRedactSecrets:
    SOURCE = {
        "name": "prod",
        "connection": {
            "host": "db.example.com",
            "username": "hound",
            "password": "hunter2",
            "key_passphrase": "opensesame",
        },
    }

    def test_password_in_dsn_is_redacted(self):
        message = "connection failed: postgresql://hound:hunter2@db.example.com/prod"
        assert "hunter2" not in _redact_secrets(message, self.SOURCE)
        assert "***" in _redact_secrets(message, self.SOURCE)

    def test_all_secret_keys_redacted_but_not_identifiers(self):
        message = "auth error for hound@db.example.com: bad hunter2 / opensesame"
        redacted = _redact_secrets(message, self.SOURCE)
        assert "hunter2" not in redacted and "opensesame" not in redacted
        assert "hound" in redacted and "db.example.com" in redacted

    def test_source_without_connection(self):
        assert _redact_secrets("boom", {"name": "x"}) == "boom"
