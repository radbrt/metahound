#!/usr/bin/env bash
# Integration test: real scans against a live Postgres and SFTP server.
#
# Expects:
#   - Postgres on localhost:5432 (user metahound / hound / db ci), seeded with seed.sql
#   - atmoz/sftp on localhost:2222 (user hound / woof, chrooted with an upload dir),
#     container name "metahound-sftp", seeded with sftp_files/orders_2026-07-01.csv
#   - metahound installed with the postgres extra
#
# CI wires this up in .github/workflows/ci.yml; locally use docker-compose.yml
# in this directory and run: bash run.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORKDIR="$(mktemp -d)"
cd "$WORKDIR"

export PGPASSWORD=hound
PSQL="psql -h localhost -p 5432 -U metahound -d ci -q"

fail() { echo "FAIL: $1" >&2; exit 1; }

# --- project setup ---------------------------------------------------------
cat > metahound.yaml <<'YAML'
version: 1
sources:
  - name: ci_pg
    type: database
    analyze: true
    connection:
      host: localhost
      port: 5432
      username: metahound
      password: hound
      drivername: postgresql
    databases:
      - ci
  - name: ci_sftp
    type: sftp
    search_prefix: /upload
    get_schemas: true
    connection:
      host: localhost
      port: 2222
      username: hound
      password: woof
    filesets:
      - name: orders
        pattern: "orders_{date}.csv"
YAML
echo "METAHOUND_BACKEND_URI=sqlite:///integration.db" > .env

metahound backend

# --- scan 1: baseline ------------------------------------------------------
metahound scan
metahound changes --fail-on breaking || fail "baseline scan must not report breaking changes"
metahound status | grep -qi "ci_pg\|source" || fail "status should mention scanned sources"
echo "PASS baseline scan"

# --- mutate both sources ---------------------------------------------------
$PSQL -c "ALTER TABLE orders DROP COLUMN status;"
$PSQL -c "ALTER TABLE orders ADD COLUMN discount numeric;"

sleep 2  # new files must land above the mtime highwater of scan 1
# a deviating orders file (different columns) and an unexpected file
printf 'id,name,category\n9,iota,x\n10,kappa,y\n11,lambda,z\n12,mu,x\n13,nu,y\n14,xi,z\n15,omicron,x\n16,pi,y\n' > orders_2026-07-02.csv
printf 'foo,bar\n1,2\n3,4\n5,6\n7,8\n9,10\n11,12\n' > mystery_report.csv
docker cp orders_2026-07-02.csv metahound-sftp:/home/hound/upload/
docker cp mystery_report.csv metahound-sftp:/home/hound/upload/

# --- scan 2: drift ---------------------------------------------------------
metahound scan
CHANGES="$(metahound changes)"
echo "$CHANGES"

echo "$CHANGES" | grep -q "column_removed"      || fail "expected column_removed for orders.status"
echo "$CHANGES" | grep -q "column_added"        || fail "expected column_added for orders.discount"
echo "$CHANGES" | grep -q "file_schema_changed" || fail "expected file_schema_changed for deviating orders file"
echo "$CHANGES" | grep -q "unrecognized_file"   || fail "expected unrecognized_file for mystery_report.csv"

if metahound changes --fail-on breaking; then
  fail "changes --fail-on breaking must exit non-zero after breaking drift"
fi
echo "PASS drift scan and pipeline gating"

# --- warnings runs over collected metrics ----------------------------------
metahound warnings --algorithm zindex || fail "warnings must run cleanly"
echo "PASS warnings"

echo "ALL INTEGRATION CHECKS PASSED"
