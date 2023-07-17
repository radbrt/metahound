import fsspec

class SFTPFileSystem():
    def __init__(self, host, username, password, port=22, search_prefix='./'):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.search_prefix = search_prefix

        self.connection = fsspec.filesystem('sftp', host=self.host, username=self.username, password=self.password)


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
