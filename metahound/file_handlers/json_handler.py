import io
import json
import logging

from metahound.json_schema import generate_schema
from metahound.file_handlers.encoding import detect_stream_encoding

logger = logging.getLogger(__name__)

MAX_SAMPLE_RECORDS = 1000


class JSONHandler():
    """
    File handler for plain JSON files (a single document, unlike JSONL).
    An array of objects is treated as records; a single object as one record.
    Args:
        file_stream (file): Binary file stream of the file to be processed
        file_name (str): Name of the file to be processed, used for metadata
        get_schema (bool): Whether or not to generate a schema for the file
    """
    def __init__(self, file_stream, file_name, get_schema=False):
        self.encoding = detect_stream_encoding(file_stream)
        self.filestream = io.TextIOWrapper(file_stream, encoding=self.encoding)
        self.get_schema = get_schema
        self.accepted_file_types = ['json']

        self.file_name = file_name

    def get_file_metadata(self):
        schema = {}
        num_rows = None

        if self.get_schema:
            try:
                document = json.load(self.filestream)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("Could not parse %s as JSON: %s", self.file_name, exc)
                return {'file': self.file_name, 'properties': {}, 'file_encoding': self.encoding}

            if isinstance(document, list):
                num_rows = len(document)
                samples = [r for r in document[:MAX_SAMPLE_RECORDS] if isinstance(r, dict)]
            elif isinstance(document, dict):
                num_rows = 1
                samples = [document]
            else:
                samples = []

            if samples:
                schema = generate_schema(samples)

        result = {'file': self.file_name, 'properties': schema, 'file_encoding': self.encoding}
        if num_rows is not None:
            result['num_rows'] = num_rows
        return result
