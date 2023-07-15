import csv
from metadog.json_schema import generate_schema
import io

class CSVHandler():
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
    def __init__(self, file_stream, file_name, get_schema=False, delimiter=None):
        self.filestream = io.TextIOWrapper(file_stream, encoding='utf-8')
        self.get_schema = get_schema
        self.delimiter = delimiter or self.get_delimiter()
        self.accepted_file_types = ['csv']

        self.file_name = file_name


    def get_file_metadata(self):
        if self.has_header() and self.get_schema:   

            t, samples = self.sample_file(sample_rate=100, max_records=1000)
            schema = generate_schema(samples)
        else:
            schema = {}

        return {'file': self.file_name, 'properties': schema}


    def has_header(self):
        """
        Check if the file has a header
        Returns:
            bool: True if the file has a header, False otherwise
        """
        csv_test_bytes = self.filestream.read(5000)
        sniffer = csv.Sniffer()
        has_header = sniffer.has_header(csv_test_bytes)
        self.filestream.seek(0)
        return has_header


    def get_delimiter(self):
        """
        Infer the delimiter of the CSV file
        Returns:
            str: Delimiter of the CSV file
        """
        csv_test_bytes = self.filestream.read(5000)
        sniffer = csv.Sniffer()
        delimiter = sniffer.sniff(csv_test_bytes).delimiter
        self.filestream.seek(0)

        return delimiter


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
        fullfile = self.filestream.readlines(max_records)
        csvfile = csv.DictReader(fullfile, fieldnames=None, delimiter=self.delimiter)
        samples = []


        current_row = 0
        for row in csvfile:
            if (current_row % sample_rate) == 0:
                samples.append(row)

            current_row += 1

            if len(samples) >= max_records:
                break

        # Empty sample to show field selection, if needed
     # Empty sample to show field selection, if needed
        empty_file = False
        if csvfile.fieldnames is None:
            empty_file = True
            samples.append({})
        else:
            samples.append({name: None for name in csvfile.fieldnames})

        self.filestream.seek(0)
        return (empty_file, samples)

