# Metahound

An open-source, headless observability tool for data engineers.

## The goal of Metahound

Metahound is designed to easily scan data sources like databases, SFTP servers and cloud storage through a declarative YAML configuration.

This enables you to:
- Keep an inventory of data sources and track changes over time
- Scan and profile database tables (schemas, row counts, statistics)
- Automatically detect anomalies in table metrics
- Store and track results in a PostgreSQL or SQLite backend

## What it is (and isn't)

The core Metahound CLI is **headless** — it has no built-in dashboard and writes everything to a database you control. This is intentional: direct database access to a sensible data model is safer and more flexible than yet another REST API. Build your own dashboard on top, or query the database directly.

An optional **self-hosted server** component (`server/`) provides a REST API and basic web UI for teams who want a centralized metadata store and a starting point for a dashboard.

## Get started

Install the package and initialize a project:

```sh
pip install metahound
metahound init <name-of-project>
```

Database drivers, cloud-storage libraries and the Prophet forecaster are optional extras — install
only what you need:

```sh
pip install 'metahound[snowflake]'   # Snowflake sources
pip install 'metahound[postgres]'    # PostgreSQL sources or a PostgreSQL backend
pip install 'metahound[bigquery]'    # BigQuery sources
pip install 'metahound[oracle]'      # Oracle sources
pip install 'metahound[mssql]'       # SQL Server sources
pip install 'metahound[s3]'          # S3 file sources
pip install 'metahound[azure]'       # Azure Blob file sources
pip install 'metahound[prophet]'     # Prophet-based anomaly detection (z-index works without it)
pip install 'metahound[all]'         # everything
```

SQLite backends, SFTP sources and local files work with the base install.

This creates a new folder with the base files needed to get started, including a `metahound.yaml` configuration file and a `.env` file for secrets.

### Set up the backend

By default, Metahound uses a local SQLite database named `metahound.db`. Initialize it with:

```sh
metahound backend
```

To use PostgreSQL instead, set the `METAHOUND_BACKEND_URI` environment variable before running `metahound backend`:

```sh
export METAHOUND_BACKEND_URI='postgresql+psycopg2://user:password@localhost:5432/mydb'
```

## Configuring sources

Edit `metahound.yaml` to define the sources you want to scan. The file supports Jinja2 templating, so secrets can be pulled from your `.env` file.

```yaml
version: 1
sources:
  - name: my_snowflake
    type: snowflake
    connection:
      account: my_account
      user: my_user
      warehouse: my_warehouse
      role: my_role
      password: {{ SNOWFLAKE_PASSWORD }}
    databases:
      - DWH
      - SOURCE_DATA

  - name: my_postgres
    type: database
    flavor: postgres
    connection:
      drivername: postgresql+psycopg2
      host: postgres.db.local
      port: 5432
      username: my_user
      password: {{ PG_PASSWORD }}
    databases:
      - postgres

  - name: my_sftp
    type: sftp
    get_schemas: true
    search_prefix: data/
    connection:
      host: 127.0.0.1
      username: my_user
      password: {{ SFTP_PASSWORD }}
      port: 22

  - name: my_s3_bucket
    type: s3
    bucket: s3://my-bucket
    get_schemas: true
    connection:
      anon: true

  - name: my_azure_storage
    type: az
    path: my-container
    get_schemas: true
    connection:
      account_name: my_storage_account
      account_key: {{ AZURE_KEY }}
```

### Supported source types

| Type | Description |
|------|-------------|
| `snowflake` | Snowflake data warehouse |
| `database` | Generic SQL database (PostgreSQL, MySQL, etc.) |
| `bigquery` | Google BigQuery (requires `pip install metahound[bigquery]`) |
| `oracle` | Oracle Database (requires `pip install metahound[oracle]`) |
| `mssql` | Microsoft SQL Server (requires `pip install metahound[mssql]`) |
| `sftp` | Remote SFTP servers |
| `s3` | AWS S3 (or S3-compatible) blob storage |
| `az` | Azure Storage Accounts |

**BigQuery example:**

```yaml
  - name: my_bigquery
    type: bigquery
    connection:
      project: my-gcp-project
      credentials_path: /path/to/service-account.json  # optional; omit to use ADC
    datasets:
      - my_dataset
```

**Oracle example** (`pip install metahound[oracle]`):

```yaml
  - name: my_oracle
    type: oracle
    connection:
      host: oracle.db.local
      port: 1521
      username: my_user
      password: {{ ORACLE_PASSWORD }}
      service_name: ORCLPDB1
```

Oracle connects to a single service (identified by `service_name`) and enumerates all schemas within it. There is no `databases` list — the service itself is the top-level scan target. `port` defaults to `1521`. An optional `driver` key can be set to `cx_oracle` if you prefer the legacy driver; the default is `oracledb`.

**MSSQL example** (`pip install metahound[mssql]`):

```yaml
  - name: my_sqlserver
    type: mssql
    connection:
      host: sqlserver.db.local
      port: 1433
      username: my_user
      password: {{ MSSQL_PASSWORD }}
    databases:
      - sales
      - inventory
```

`port` defaults to `1433`. An optional `driver` key can be set to `pyodbc` if you have ODBC drivers installed; the default is `pymssql`.

See `metahound/connection_handlers/README.md` for full connection configuration details.

### Supported file formats

Files discovered on SFTP, S3, and Azure sources are parsed for schema and statistics:

- CSV
- Parquet
- JSONL

### Keep secrets out of config

Reference secrets from your `.env` file using Jinja2 double-brace notation:

```yaml
password: {{ MY_SECRET_PASSWORD }}
```

Define the corresponding value in `.env`:

```
MY_SECRET_PASSWORD=sup3rs3cret!
```

## Running metahound

### Scan sources

```sh
metahound scan
```

Parses the configuration file, scans each source, and writes results to the backend database. Options:

- `-s / --select <names>` — scan only the named source(s), comma-separated

- `--no-stats` — skip collecting table statistics (faster)

### Check for schema changes

Every scan records a snapshot of each source's schema and diffs it against the
previous scan. The first scan of a source establishes a silent baseline; after
that, changes are recorded as events:

```sh
metahound changes
```

Each change is classified as **breaking** (column removed, column type changed,
table removed, file schema changed) or **info** (table, column or file added).
By default the command shows changes from the most recent scan of each source;
use `--since <ISO timestamp>` to look further back.

To gate an ingest pipeline, run a scan followed by `changes --fail-on` in a
pre-ingest task (Airflow, Dagster, cron, CI):

```sh
metahound scan && metahound changes --fail-on breaking
```

The command exits non-zero if any breaking change (or with `--fail-on any`,
any change at all) was detected, so the pipeline stops before bad data lands.

### Check for anomalies

After running at least two scans, detect anomalies in collected metrics:

```sh
metahound warnings
```

Two algorithms are available via the `-a / --algorithm` flag:

- `zindex` (default) — statistical Z-score based detection
- `prophet` — Facebook Prophet time-series forecasting

The Z-score threshold can be overridden with `-t / --threshold`:

```sh
metahound warnings --threshold 2.5
```

The default threshold is `3.0`. A lower value flags more anomalies; a higher value flags fewer. The threshold can also be set per-source in `metahound.yaml`.

### Check status

Print a summary of all sources and recent scans stored in the backend:

```sh
metahound status
```

### Push to a Metahound server

If you're running the self-hosted server or using Metahound Cloud, push local scan results with:

```sh
metahound push --api-url https://your-server.example.com --token <your-token>
```

Store the URL and token locally to avoid passing them on every run:

```sh
metahound config set-url https://your-server.example.com
metahound config set-token <your-token>
```

These are saved to your `.env` file as `METAHOUND_API_URL` and `METAHOUND_API_TOKEN`.

## CLI reference

| Command | Description |
|---------|-------------|
| `metahound init <name>` | Initialize a new project folder |
| `metahound backend` | Set up the backend database schema |
| `metahound scan` | Run a scan of configured sources |
| `metahound changes` | Show schema changes detected by scans; `--fail-on` gates pipelines |
| `metahound warnings` | Detect anomalies in collected metrics |
| `metahound status` | Print a summary of sources and recent scans |
| `metahound push` | Push local data to a Metahound server |
| `metahound config set-token <token>` | Save API token to `.env` |
| `metahound config set-url <url>` | Save server URL to `.env` |

Pass `-v / --verbose` to any command for debug-level logging.

## Q&A

**Q**: Why doesn't metahound use a standard data model like \<insert-your-favorite-metadata-standard\>?

**A**: Some possible reasons include:
- It was too complex and would take too much effort for users to understand
- It didn't contain some fields I wanted
- I didn't know about it

**Q**: Will Metahound do lineage?

**A**: Probably not, because scanning data sources is distinct from the code that produces lineage. It would be cool to have a lineage tool compatible with the metahound backend though.
