import fsspec

class S3FileSystem():
    def __init__(self, search_prefix=None, storage_options={'anon': True}):

        self.storage_options = storage_options
        self.search_prefix = search_prefix

        self.connection = fsspec.filesystem('s3', **storage_options)


    @property
    def uri(self):
        return f"s3://{self.search_prefix}"

    def get_files(self):
        fl = self.connection.ls(self.search_prefix, detail=True)
        fl_formatted = [
            {
                'name': f['Key'], 
                'size': f['Size'], 
                'mtime': f['LastModified'].replace(tzinfo=None)
            } for f in fl
                if f['size'] > 0 and not f['Key'].endswith('/')
                ]
        
        return fl_formatted


    def get_file(self, file_name):
        file_stream = self.connection.open(file_name, 'rb')

        return file_stream
    
    def get_last_modified(self):
        fl = self.connection.ls(self.search_prefix, detail=True)
        max_time = max([f['LastModified'] for f in fl])
        return max_time
