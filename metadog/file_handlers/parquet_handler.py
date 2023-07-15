import pyarrow.parquet as pq
import io

class ParquetHandler():
    """
    File handler for Parquet files
    Args:
        file_stream (file): Binary file stream of the file to be processed,
        this is part of the generic interface for all file handlers
        file_name (str): Name of the file to be processed, used for metadata
        get_schema (bool): Whether or not to return the schema for the file
    """
    def __init__(self, file_stream, file_name, get_schema=False):
        self.parquet_file = pq.ParquetFile(file_stream)
        self.get_schema = get_schema
        self.accepted_file_types = ['parquet']

        self.file_name = file_name


    def get_file_metadata(self):
        """
        Get the metadata for the file
        Returns:
            dict: Dictionary containing the file name and the schema
        """
        schema = {}
        if self.get_schema:
            for i in range(self.parquet_file.metadata.num_columns):
                col = self.parquet_file.schema.column(i)
                schema[col.name] = { 'type': [str(col.logical_type)] }

            return {'file': self.file_name, 'properties': schema}

        return {'file': self.file_name, 'properties': schema}

