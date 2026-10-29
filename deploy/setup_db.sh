#!/usr/bin/env bash
# Setup PostgreSQL 16 + PostGIS on Ubuntu 22.04/24.04
set -euo pipefail

# 1. Add PostgreSQL official repo
apt-get update
apt-get install -y wget ca-certificates gnupg lsb-release
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg
echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list

# 2. Install PostgreSQL 16 and PostGIS 3
apt-get update
apt-get install -y postgresql-16 postgresql-16-postgis-3 postgresql-16-postgis-3-scripts

# 3. Create app user & database
sudo -u postgres psql -c "CREATE ROLE geoptt WITH LOGIN PASSWORD '${DB_PASSWORD:-geoptt}';"
sudo -u postgres psql -c "CREATE DATABASE geoptt OWNER geoptt;"
sudo -u postgres psql -d geoptt -c "CREATE EXTENSION postgis; CREATE EXTENSION pgcrypto;"

# 4. Run alembic migrations (assumes repo cloned at /opt/geoptt and venv at /opt/geoptt/.venv)
cd /opt/geoptt
/opt/geoptt/.venv/bin/alembic upgrade head

echo "✅ PostgreSQL + PostGIS ready and migrations applied."