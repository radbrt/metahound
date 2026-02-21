# Metadog

An open-source, headless observability tool for data engineers.

## The goal of Metadog

Metadog is designed to easily scan data sources like databases, SFTP servers and cloud storage through a declarative YAML configuration.

This enables you to:
- Keep an inventory of data sources and track changes over time
- Scan and profile database tables (schemas, row counts, statistics)
- Automatically detect anomalies in table metrics
- Store and track results in a PostgreSQL or SQLite backend

## What it is (and isn't)

The core Metadog CLI is **headless** — it has no built-in dashboard and writes everything to a database you control. This is intentional: direct database access to a sensible data model is safer and more flexible than yet another REST API. Build your own dashboard on top, or query the database directly.

An optional **self-hosted server** component (`server/`) provides a REST API and basic web UI for teams who want a centralized metadata store and a starting point for a dashboard.

## Get started

Install the package and initialize a project:

```sh
pip install metadog
metadog init <name-of-project>
```

This creates a new folder with the base files needed to get started, including a `metadog.yaml` configuration file and a `.env` file for secrets.

### Set up the backend

By default, Metadog uses a local SQLite database named `metadog.db`. Initialize it with:

```sh
metadog backend
```

To use PostgreSQL instead, set the `METADOG_BACKEND_URI` environment variable before running `metadog backend`:

```sh
export METADOG_BACKEND_URI='postgresql+psycopg2://user:password@localhost:5432/mydb'
```

## Configuring sources

Edit `metadog.yaml` to define the sources you want to scan. The file supports Jinja2 templating, so secrets can be pulled from your `.env` file.

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
| `bigquery` | Google BigQuery (requires `pip install metadog[bigquery]`) |
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

See `metadog/connection_handlers/README.md` for full connection configuration details.

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

## Running metadog

### Scan sources

```sh
metadog scan
```

Parses the configuration file, scans each source, and writes results to the backend database. Options:

- `-s / --select <name>` — scan only the named source
- `--no-stats` — skip collecting table statistics (faster)

### Check for anomalies

After running at least two scans, detect anomalies in collected metrics:

```sh
metadog warnings
```

Two algorithms are available via the `-a / --algorithm` flag:

- `zindex` (default) — statistical Z-score based detection
- `prophet` — Facebook Prophet time-series forecasting

The Z-score threshold can be overridden with `-t / --threshold`:

```sh
metadog warnings --threshold 2.5
```

The default threshold is `3.0`. A lower value flags more anomalies; a higher value flags fewer. The threshold can also be set per-source in `metadog.yaml`.

### Check status

Print a summary of all sources and recent scans stored in the backend:

```sh
metadog status
```

### Push to a Metadog server

If you're running the self-hosted server or using Metadog Cloud, push local scan results with:

```sh
metadog push --api-url https://your-server.example.com --token <your-token>
```

Store the URL and token locally to avoid passing them on every run:

```sh
metadog config set-url https://your-server.example.com
metadog config set-token <your-token>
```

These are saved to your `.env` file as `METADOG_API_URL` and `METADOG_API_TOKEN`.

## CLI reference

| Command | Description |
|---------|-------------|
| `metadog init <name>` | Initialize a new project folder |
| `metadog backend` | Set up the backend database schema |
| `metadog scan` | Run a scan of configured sources |
| `metadog warnings` | Detect anomalies in collected metrics |
| `metadog status` | Print a summary of sources and recent scans |
| `metadog push` | Push local data to a Metadog server |
| `metadog config set-token <token>` | Save API token to `.env` |
| `metadog config set-url <url>` | Save server URL to `.env` |

Pass `-v / --verbose` to any command for debug-level logging.

## Q&A

**Q**: Why doesn't metadog use a standard data model like \<insert-your-favorite-metadata-standard\>?

**A**: Some possible reasons include:
- It was too complex and would take too much effort for users to understand
- It didn't contain some fields I wanted
- I didn't know about it

**Q**: Will Metadog do lineage?

**A**: Probably not, because scanning data sources is distinct from the code that produces lineage. It would be cool to have a lineage tool compatible with the metadog backend though.
