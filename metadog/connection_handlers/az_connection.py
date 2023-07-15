import fsspec

class AZFileSystem():
    def __init__(self, search_prefix=None, storage_options={}):

        self.storage_options = storage_options
        self.search_prefix = search_prefix

        self.connection = fsspec.filesystem('az', **storage_options)


    @property
    def uri(self):
        return f"az://{self.storage_options['account_name']}/{self.search_prefix}"


    def get_files(self):

        for f in self.list_files_recursive(self.search_prefix):
            yield {
                'name': f['name'], 
                'size': f['size'], 
                'mtime': f['last_modified'].replace(tzinfo=None)
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
        fl = self.list_files_recursive(self.search_prefix)
        max_time = max([f['last_modified'] for f in fl])
        return max_time
