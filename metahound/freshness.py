import json
from sqlalchemy import create_engine, MetaData, Table, select, func
import pandas as pd
from sqlalchemy import select, func, text
from sqlalchemy.sql import column
from scipy.stats import zscore

def report_freshness(manifest_path, engine):
    """
    Find the loaded_at fields in sources in the dbt manifest,
    selects the loaded_at field from each table and compare to current timestamp for freshness.
    """

    parsed_manifest = json.load(open(manifest_path, "r"))

    for source_name in parsed_manifest["sources"].keys():
        source = parsed_manifest["sources"][source_name]
        loaded_at = source.get("loaded_at")
        if loaded_at:
            db = source["database"]
            schema = source["schema"]
            table = source["name"]

            metadata = MetaData(bind=engine, schema=schema)
            table = Table(table, metadata, autoload=True)

            # Calculate the z-score for the elapsed time column in SQL
            elapsed_time = column('elapsed_time')
            z_score = func.abs((elapsed_time - func.avg(elapsed_time).over()) / func.stddev_pop(elapsed_time).over()).label('z_score')
            stmt = select([table.c.loaded_at, elapsed_time, z_score]).order_by(table.c.loaded_at.desc()).limit(2)

            # Execute the SQL statement and retrieve the results as a DataFrame
            df = pd.read_sql(stmt, engine)

            # Calculate the z-score for the elapsed time column
            df['z_score'] = zscore(df['elapsed_time'])

            # Get the row with the highest loaded_at timestamp
            latest_row = df.loc[df['loaded_at'].idxmax()]

            # Print the row with the z-score for the newest row
            print(latest_row)


