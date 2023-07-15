# from sqlalchemy import create_engine, inspect
# import fsspec
# import csv
# from .json_schema import sample_file, generate_schema
# from .setup import Sources, Files, Fields, TableMetrics, Tables, ColumnMetrics
# from sqlalchemy.orm import sessionmaker
# import os

# def profile_files(protocol, domain, filetype='csv', get_schema=True, n_samples=1000, **kwargs):
#     fs = fsspec.filesystem(protocol, **kwargs)
#     fl = fs.ls('./')
#     csvs = [f for f in fl if f.endswith(f'.{filetype}')]

#     schemas = []
#     for file in csvs:
#         with fs.open(file, 'r') as fin:
#             csv_test_bytes = fin.read(5000)
#             sniffer = csv.Sniffer()
#             has_header = sniffer.has_header(csv_test_bytes)
#             if has_header and get_schema:   
#                 delimiter = sniffer.sniff(csv_test_bytes).delimiter
#                 fin.seek(0)
#                 fullfile = fin.readlines()
#                 csvfile = csv.DictReader(fullfile, fieldnames=None, delimiter=delimiter)
#                 t, samples = sample_file(csvfile, has_header=has_header, sep=delimiter, sample_rate=100, max_records=1000)
#                 schema = generate_schema(samples)
#             else:
#                 schema = None
#         schemas.append({'file': file, 'properties': schema})
    
#     merge_file_crawl(domain=domain, protocol=protocol, file_list=schemas)

#     return schemas


# def get_file_list(protocol, **kwargs):
#     fs = fsspec.filesystem(protocol, **kwargs)
#     return fs.ls('./')


# def merge_file_crawl(domain, protocol, file_list):
#     print("Merging file crawl")
#     connect_string = os.getenv("METADOG_BACKEND_URI") or 'sqlite:///metadog.db'
#     engine = create_engine(connect_string)
#     Session = sessionmaker(bind=engine)
#     session = Session()

#     source_uri = f"{protocol}://{domain}/"
#     source = session.query(Sources).filter_by(uri=source_uri).first()

#     if not source:
#         source = Sources(name=domain, type=protocol, uri=source_uri)

#     for file in file_list:
#         file_uri = f"{source_uri}/{file['file']}"

#         file_entry = session.query(Files).filter_by(uri=file_uri).first()
#         if not file_entry:
#             file_entry = Files(name=file['file'], uri=file_uri, filetype='csv', file_encoding='utf-8')

#         for column in file['properties'].keys():
#             column_uri = f"{file_uri}/{column}"
#             column_types = '/'.join([ f_type for f_type in file['properties'][column]['type'] if f_type!='null'])
#             column_entry = session.query(Fields).filter_by(uri=column_uri).first()
#             if not column_entry:
#                 column_entry = Fields(name=column, type=column_types, uri=column_uri)

#             file_entry.fields.append(column_entry)
#         source.files.append(file_entry)

#     session.merge(source)
#     # Commit the session to write the data to the database
#     session.commit()
#     session.close()

