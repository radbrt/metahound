from sqlalchemy import create_engine, MetaData, Table, select, func, Numeric, Integer, String, distinct

def analyze_table(tbl_name, schema, engine):

    metadata = MetaData(schema=schema)
    table = Table(tbl_name, metadata, autoload=True, autoload_with=engine)

    # Get the numeric columns
    numeric_columns = [column for column in table.columns if isinstance(column.type, (Numeric, Integer))]
    char_columns = [column for column in table.columns if isinstance(column.type, String)]
    # Generate min, avg, and max values for each numeric column
    numeric_selects = []
    for column in numeric_columns:
        numeric_selects += [
            func.min(column).label(f"{column.name}__min"),
            func.avg(column).label(f"{column.name}__avg"),
            func.max(column).label(f"{column.name}__max"),
            func.count(column).label(f"{column.name}__null_count")
        ]

    char_selects = []
    for column in char_columns:
        char_selects += [
            func.count(distinct(column)).label(f"{column.name}__unique_count"),
            func.count(column).label(f"{column.name}__null_count")
        ]

    all_selects = numeric_selects + char_selects + [func.count()]
    stmt = select(all_selects)
    with engine.connect() as conn:
        result = conn.execute(stmt)
        result_dict = [dict(row) for row in result]

    return result_dict
