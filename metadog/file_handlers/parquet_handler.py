import pyarrow.parquet as pq
import io

class ParquetHandler():

    def __init__(self, file_stream, file_name, get_schema=False, delimiter=None):
        self.parquet_file = pq.ParquetFile(file_stream)
        self.get_schema = get_schema
        self.accepted_file_types = ['parquet']

        self.file_name = file_name


    def get_file_metadata(self):
        schema = {}
        if self.get_schema:
            for i in range(self.parquet_file.metadata.num_columns):
                col = self.parquet_file.schema.column(i)
                schema[col.name] = { 'type': [str(col.logical_type)] }

            return {'file': self.file_name, 'properties': schema}

        return {'file': self.file_name, 'properties': schema}

