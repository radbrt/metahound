import logging

from metahound.json_schema import generate_schema

logger = logging.getLogger(__name__)

MAX_SAMPLE_ROWS = 1000


class ExcelHandler():
    """
    File handler for Excel (.xlsx) files. Reads the first worksheet; the
    first row is the header. Requires the `excel` extra (openpyxl) — without
    it the file is treated like any unhandled format.
    Args:
        file_stream (file): Binary file stream of the file to be processed
        file_name (str): Name of the file to be processed, used for metadata
        get_schema (bool): Whether or not to generate a schema for the file
    """
    def __init__(self, file_stream, file_name, get_schema=False):
        self.filestream = file_stream
        self.get_schema = get_schema
        self.accepted_file_types = ['xlsx']

        self.file_name = file_name

    def get_file_metadata(self):
        schema = {}
        num_rows = None

        if self.get_schema:
            try:
                import openpyxl
            except ImportError:
                logger.warning(
                    "openpyxl is not installed — cannot infer schema for %s. "
                    "Install with: pip install 'metahound[excel]'", self.file_name,
                )
                return {'file': self.file_name, 'properties': {}}

            workbook = openpyxl.load_workbook(self.filestream, read_only=True, data_only=True)
            try:
                sheet = workbook.worksheets[0]
                rows = sheet.iter_rows(values_only=True)
                header = next(rows, None)

                if header and any(h is not None for h in header):
                    columns = [str(h) for h in header]
                    samples = []
                    num_rows = 0
                    for row in rows:
                        num_rows += 1
                        if len(samples) < MAX_SAMPLE_ROWS:
                            samples.append(dict(zip(columns, row)))
                    if samples:
                        schema = generate_schema(samples)
                    else:
                        schema = {name: {'type': ['string']} for name in columns}
            finally:
                workbook.close()

        result = {'file': self.file_name, 'properties': schema}
        if num_rows is not None:
            result['num_rows'] = num_rows
        return result
