#!/bin/bash
# Run on bolls as root: ssh bolls 'bash -s' < setup_db_role.sh
# Creates/updates the read-only role ops_ro in the scraper's Postgres and writes /opt/miles-ops/.env (chmod 600).
# Never prints secrets.
set -euo pipefail
mkdir -p /opt/miles-ops/data
cd /opt/miles-scraper
set -a; . ./.env; set +a
if [ ! -s /opt/miles-ops/.env ] || ! grep -q '^OPS_DB_DSN=' /opt/miles-ops/.env; then
  PW=$(openssl rand -hex 24)
  ( umask 077; printf 'OPS_DB_DSN=postgresql://ops_ro:%s@127.0.0.1:55432/%s\n' "$PW" "$DB_NAME" > /opt/miles-ops/.env )
fi
chmod 600 /opt/miles-ops/.env
PW=$(sed -n 's#^OPS_DB_DSN=postgresql://ops_ro:\([^@]*\)@.*#\1#p' /opt/miles-ops/.env)
{
  printf '\\set pw %s\n' "$PW"
  printf '\\set db %s\n' "$DB_NAME"
  cat <<'SQL'
\set ON_ERROR_STOP on
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ops_ro') THEN CREATE ROLE ops_ro LOGIN; END IF;
END $$;
ALTER ROLE ops_ro WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 5 PASSWORD :'pw';
ALTER ROLE ops_ro SET default_transaction_read_only = on;
ALTER ROLE ops_ro SET statement_timeout = '30s';
GRANT CONNECT ON DATABASE :"db" TO ops_ro;
GRANT USAGE ON SCHEMA public TO ops_ro;
REVOKE CREATE ON SCHEMA public FROM ops_ro;
GRANT SELECT ON vehicle_changes, vehicle_changes_city, "MilesVehicleLastKnown", "MilesVehicle", "MilesVehicleModel",
                "MilesVehicleSize", "MilesCity", "MilesVehicleDamage" TO ops_ro;
SELECT 'role ok' AS status, count(*) AS tables_granted FROM information_schema.role_table_grants WHERE grantee = 'ops_ro';
SQL
} | docker compose exec -T postgres psql -q -U "$DB_USER" -d "$DB_NAME"
