
import csv
import io


# def get_row_iterator(iterable, sep=','):
#     """Accepts an interable, options and returns a csv.DictReader object
#     which can be used to yield CSV rows."""

#     reader = csv.DictReader(
#         iterable,
#         delimiter=sep
#     )

#     return reader

def convert_schema_to_singer(schema):
    """
    Convert a schema from sqlalchemy to a singer schema.
    Not used, not finished.
    """
    singer_schema = {
        "type": ["object"],
        "properties": {},
        "additionalProperties": False,
    }

    for column in schema:
        singer_schema["properties"][column["name"]] = {
            "type": str(column["type"]),
        }

    return singer_schema

def convert_schema_to_openlineage(schema, namespace, name):
    """
    Convert a schema from sqlalchemy to an openlineage schema.
    """
    openlineage_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    for column in schema:
        openlineage_schema["properties"][column["name"]] = {
            "type": str(column["type"].as_generic()),
        }

    return openlineage_schema


def sample_file(reader, has_header=True, sep=',', sample_rate=100, max_records=1000):
    samples = []


    current_row = 0
    for row in reader:
        if (current_row % sample_rate) == 0:
            samples.append(row)

        current_row += 1

        if len(samples) >= max_records:
            break

    # Empty sample to show field selection, if needed
    empty_file = False
    if len(samples) == 0:
        empty_file = True
        # Assumes all reader objects in readers have the same fieldnames
        samples.append({name: None for name in reader.fieldnames})

    return (empty_file, samples)




def infer_datatype(datum):
    """
    Returns the inferred data type
    """
    if datum is None or datum == '':
        return None

    try:
        int(datum)
        return 'integer'
    except (ValueError, TypeError):
        pass

    try:
        # numbers are NOT floats, they are DECIMALS
        float(datum)
        return 'number'
    except (ValueError, TypeError):
        pass

    return 'string'


def count_sample(sample, type_summary):
    """
        Generates a summary dict of each column and its inferred types
        {'Column1': {'string': 10}, 'Column2': {'integer': 10}}
    """
    for key, value in sample.items():
        if key not in type_summary:
            type_summary[key] = {}


        datatype = infer_datatype(value)

        if datatype is not None:
            type_summary[key][datatype] = type_summary[key].get(datatype, 0) + 1

    return type_summary

def pick_datatype(type_count):
    """
    If the underlying records are ONLY of type `integer`, `number`,
    or `date-time`, then return that datatype.
    If the underlying records are of type `integer` and `number` only,
    return `number`.
    Otherwise return `string`.
    """
    to_return = 'string'

    if type_count.get('date-time', 0) > 0:
        return 'date-time'

    if len(type_count) == 1:
        if type_count.get('integer', 0) > 0:
            to_return = 'integer'
        elif type_count.get('number', 0) > 0:
            to_return = 'number'

    elif (len(type_count) == 2 and type_count.get('integer', 0) > 0 and type_count.get('number', 0) > 0):
        to_return = 'number'

    return to_return


def generate_schema(samples):
    type_summary = {}
    for sample in samples:
        type_summary = count_sample(sample, type_summary)

    schema = {}
    for key, value in type_summary.items():

        datatype = pick_datatype(value)

        if datatype == 'date-time':
            schema[key] = {
                'anyOf': [
                    {'type': ['null', 'string'], 'format': 'date-time'},
                    {'type': ['null', 'string']}
                ]
            }
        else:
            types = ['null', datatype]
            if datatype != 'string':
                types.append('string')
            schema[key] = {
                'type': types,
            }

    return schema

