# Metadog

An open-source, headless observability tool.

## The goal of Metadog
Metadog is designed to easily scan data sources like databases, SFTP servers and cloud storage through a declarative yaml configuration.

This enables you to:
- Keep an inventory of the data sources, and track changes
- Scan and profile database tables
- Automatically monitor for anomalies in table statistics
- Store and track the results in a postgres or sqlite database (more backends coming)


## What it is not
Metadog is not a dashboard for your data. Metadog is completely headless, but is designed to provide read-access to other tools. Make your own dashboard, if you want one.

Metadog does not have an API. We believe it is both safer and more useful for data teams to have direct database access to a sensible data model rather than yet another REST API to deal with. In other words, Metadog is RESTless.


## Get started

Initialize a project with `metadog init <name-of-project>`. This will create a new folder with the base files you need to get started.

By default, Metadog will use a SQLite database as a backend to store the data catalog and metrics. The database will be stored in the metadog project folder, and be named `metadog.db`. If you want to use a different database, make sure to declare a database connection string either as an environment variable or in the `.env` file.

You can initialize this database by running

```sh
metadog backend
```

This will create the necessary tables to start a scan.


To define a backend database, create a `METADOG_BACKEND_URI` environment variable:

```sh
export METADOG_BACKEND_URI = 'postgresql+psycopg2://postgres:postgres@localhost/postgres:5432'
```

## Configuring soures

In `metadog.yaml`, most of the documentation will happen under the `sources` key, which contains a list of the sources that should be scanned.

Every source has a name, and a type. The name is user-specified and can be a nickname etc to make the source recognizable (especially if the server address is just an IP or random string). The type refers to the type of source: Currently, the following source types are supported:
	- snowflake (specific connector to snowflake database)
	- database (generic connector for databases)
	- sftp (remote SFTP servers)
	- s3 (blob storage)
	- az (Azure Storage Account)

The rest of the source configurations depends on the type of source and authentication method, and is documented under connection_handlers/README.md.

Choose the backend database you want to use by updating the `METADOG_BACKEND_URI` environment value in the `.env` file, or set it as a system environment variable. By default, Metadog uses a local SQLite database named `metadog.db`. The database will be created the first time metadog runs.

<!--Check that the configuration is valid by running `metadog validate`.-->

Once the validation passes, you can run a scan with `metadog scan`. You can limit the scan to only a subset of sources using the `-s` or `--select` flag, and turn off table statistics at runtime with the `--no-stats` flag.

## Running metadog

### Scanning

Once the sources have been configured, you can start a scan by running `metadog scan`. This will parse the configuration file, scan each source, and write the result to the backend database.

### Check for outliers

Once `metadog scan` has been run at least two times, you can scan the table metrics and print anomalies by running `metadog warnings`.

Metadog uses Prophet for predicting metric values, and `metadog warnings` will report any observations where the observed value is outside the lower or upper estimated threshold.

## Q&A

**Q**: Why doesn't metadog use a standard data model like <insert-your-favorite-metadata-standard>?
**A**: Some possible reasons include:
- It was way too complex, it would take too much for users to understand it
- It didn't contain some fields I wanted
- I didn't know about it

**Q**: Will Metadog do lineage?
**A**: Probably not, because scanning data sources is distinct from the code that produces the lineage. It would be cool to have a lineage tool that is compatible with the metadog backend though.

