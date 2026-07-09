# Security

Metahound connects to your production data sources, so it is designed to
need as little access as possible and to leak as little as possible.

## Reporting a vulnerability

Open a private report via GitHub Security Advisories on
[radbrt/metahound](https://github.com/radbrt/metahound/security/advisories/new),
or email the maintainer. Please do not open public issues for suspected
vulnerabilities. You can expect an initial response within a week.

## What Metahound reads

- **Databases**: schema metadata (tables, columns, types) and aggregate
  statistics (row counts, null fractions, distinct counts). With
  `analyze: false` or `--no-stats`, metadata only. Row contents are never
  stored.
- **File stores**: directory listings (names, sizes, mtimes) and, when
  `get_schemas: true`, a bounded sample of each new file to infer its
  schema. Inferred schemas (column names and types) are stored; file
  contents are not.
- **APIs** (`openapi` sources): the spec document, and for probes a single
  GET whose payload is sampled for schema inference only.
- **LLM discovery** (opt-in): prompts contain only filenames and inferred
  column names/types — never file contents, credentials, or sample rows.

The backend database therefore holds metadata (names, types, metrics,
change events), not your data.

## Credential handling

- Keep secrets in `.env` and reference them from `metahound.yaml` with
  `{{ JINJA_VARS }}`. Never commit `.env`.
- Error messages from scan failures are redacted: any configured secret
  value (passwords, passphrases, tokens, keys) is replaced with `***`
  before logging, because database drivers embed full DSNs in their
  exceptions. Full tracebacks are only emitted at DEBUG log level.
- Credentials are never written to the backend database or included in
  pushes to Metahound Cloud.

## SFTP: prefer key-based auth

```yaml
connection:
  host: sftp.partner.com
  username: metahound
  key_path: ~/.ssh/metahound_ed25519
  key_passphrase: "{{ SFTP_KEY_PASSPHRASE }}"   # only if the key has one
  port: 22
```

Password auth (`password: "{{ SFTP_PASSWORD }}"`) still works, but a
dedicated, passphrase-protected key with a read-only account is the
recommended setup.

## Least-privilege database grants

Create a dedicated read-only user for Metahound. It needs to enumerate
schemas and read tables (for statistics), nothing else.

**PostgreSQL**

```sql
CREATE ROLE metahound LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE mydb TO metahound;
GRANT USAGE ON SCHEMA public TO metahound;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO metahound;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO metahound;
```

**Snowflake**

```sql
CREATE ROLE METAHOUND_RO;
GRANT USAGE ON DATABASE MYDB TO ROLE METAHOUND_RO;
GRANT USAGE ON ALL SCHEMAS IN DATABASE MYDB TO ROLE METAHOUND_RO;
GRANT SELECT ON ALL TABLES IN DATABASE MYDB TO ROLE METAHOUND_RO;
GRANT SELECT ON FUTURE TABLES IN DATABASE MYDB TO ROLE METAHOUND_RO;
CREATE USER METAHOUND DEFAULT_ROLE = METAHOUND_RO PASSWORD = '...';
GRANT ROLE METAHOUND_RO TO USER METAHOUND;
```

**BigQuery** — grant the service account `roles/bigquery.dataViewer` on the
datasets to scan and `roles/bigquery.jobUser` on the project.

**Oracle**

```sql
CREATE USER metahound IDENTIFIED BY "...";
GRANT CREATE SESSION TO metahound;
GRANT SELECT ANY TABLE TO metahound;      -- or per-table GRANT SELECT
```

**SQL Server**

```sql
CREATE LOGIN metahound WITH PASSWORD = '...';
CREATE USER metahound FOR LOGIN metahound;
ALTER ROLE db_datareader ADD MEMBER metahound;
```

Heavy statistics (`COUNT(DISTINCT)` per string column) are off by default
and opt-in via `stats: {heavy: true}`; `stats: {sample_percent: 5}` caps
cost on large tables via `TABLESAMPLE`. Use `analyze: false` per source or
`--no-stats` if even the cheap aggregate pass is a concern.

## Metahound Cloud

`metahound push` sends catalog metadata, metrics, and change events over
HTTPS, authenticated by a workspace API token (`Bearer`). Tokens are
stored hashed server-side, can be named, expired, and revoked from the
Tokens page, and should be scoped one per pipeline/host so revocation is
surgical.
