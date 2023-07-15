import csv
from metadog.json_schema import generate_schema
import json
import io

class JSONLHandler():
    """
    Abstract class for handling CSV files
    Args:
        file_stream (file): Binary file stream of the file to be processed,
        this is part of the generic interface for all file handlers
        file_name (str): Name of the file to be processed, used for metadata
        get_schema (bool): Whether or not to generate a schema for the file
        delimiter (str): Delimiter to use for the CSV file, if not specified,
        the delimiter will be inferred
    """
    def __init__(self, file_stream, file_name, get_schema=False):
        self.filestream = io.TextIOWrapper(file_stream, encoding='utf-8')
        self.get_schema = get_schema
        self.accepted_file_types = ['jsonl']

        self.file_name = file_name


    def get_file_metadata(self):
        if self.get_schema:   

            t, samples = self.sample_file(sample_rate=100, max_records=1000)
            schema = generate_schema(samples)
        else:
            schema = {}

        return {'file': self.file_name, 'properties': schema}



    def sample_file(self, sample_rate=100, max_records=1000):
        """
        Sample the file to get a schema
        Args:
            sample_rate (int): How often to sample the file
            max_records (int): Maximum number of records to sample
        Returns:
            tuple: Tuple of (empty_file, samples), where empty_file is a bool
            indicating whether or not the file was empty, and samples is a list
            of samples from the file
        """

        samples = []

        current_row = 0
        for row in self.filestream.readlines(max_records):
            if (current_row % sample_rate) == 0:
                samples.append(json.loads(row))

            current_row += 1

            if len(samples) >= max_records:
                break

        self.filestream.seek(0)

        return (None, samples)

