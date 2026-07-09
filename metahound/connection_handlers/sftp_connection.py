import os

import fsspec


class SFTPFileSystem():
    """SFTP source filesystem.

    Authentication is key-based (key_path, optionally key_passphrase) or
    password-based; key auth wins when both are configured. Extra kwargs
    flow through fsspec to paramiko's SSHClient.connect.
    """

    def __init__(self, host, username, password=None, port=22, search_prefix='./',
                 key_path=None, key_passphrase=None):
        self.host = host
        self.username = username
        self.port = port
        self.search_prefix = search_prefix

        if not key_path and not password:
            raise ValueError(
                f"SFTP source {host}: provide 'key_path' (recommended) or 'password'"
            )

        connect_kwargs = {
            "host": self.host,
            "username": self.username,
            "port": self.port,
        }
        if key_path:
            connect_kwargs["key_filename"] = os.path.expanduser(key_path)
            if key_passphrase:
                connect_kwargs["passphrase"] = key_passphrase
        else:
            connect_kwargs["password"] = password

        self.connection = fsspec.filesystem('sftp', **connect_kwargs)


    @property
    def uri(self):
        return f"sftp://{self.username}@{self.host}"

    def get_files(self):

        for f in self.list_files_recursive(self.search_prefix):
            yield {
                'name': f['name'],
                'size': f['size'],
                'mtime': f['mtime']
            }


    def list_files_recursive(self, path):
        for file in self.connection.ls(path, detail=True):
            if file['type'] == 'directory':
                yield from self.list_files_recursive(file['name'])
            else:
                yield file


    def get_file(self, file_name):
        file_stream = self.connection.open(file_name, 'rb')

        return file_stream

    def get_last_modified(self):
        fl = self.connection.ls(self.search_prefix, detail=True)
        max_time = max([f['mtime'] for f in fl])
        return max_time
