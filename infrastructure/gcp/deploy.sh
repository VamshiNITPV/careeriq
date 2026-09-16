#!/usr/bin/env bash
# Deploy CareerIQ on the VM. Run from the repository root.
#
#   ./infrastructure/gcp/deploy.sh
#
# Safe to re-run: every step is idempotent, and it is the same script for the
# first deploy and every one after.

set -euo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"

cd "$(dirname "$0")/../.."

if [[ ! -f .env.production ]]; then
	echo "error: .env.production is missing." >&2
	echo "Copy .env.production.example and fill it in. It holds secrets and is" >&2
	echo "gitignored, so it never arrives with a clone." >&2
	exit 1
fi

# `set -a` exports everything sourced, which is how compose's ${VAR} lookups see
# POSTGRES_PASSWORD and SITE_ADDRESS. Without it they resolve empty and the
# `:?` guards in the compose file fire.
set -a
# shellcheck disable=SC1091
source .env.production
set +a

echo "==> Building"
$COMPOSE build

echo "==> Starting the database"
$COMPOSE up -d postgres
# `up -d` returns once the container is running, not once Postgres is ready.
# Migrating against a database still in recovery fails in a way that looks like
# a broken migration.
until $COMPOSE exec -T postgres pg_isready -U "${POSTGRES_USER:-careeriq}" >/dev/null 2>&1; do
	sleep 2
done

echo "==> Migrations"
# Explicitly, before anything serves traffic. Nothing runs these automatically:
# the app's lifespan seeds the skill taxonomy but never migrates, and against a
# schema-less database that seeding logs an error and carries on — so the API
# would come up looking healthy and be unusable.
$COMPOSE run --rm --no-deps backend alembic upgrade head

echo "==> Building the frontend bundle"
$COMPOSE up --exit-code-from frontend-build frontend-build

echo "==> Starting"
$COMPOSE up -d backend caddy

echo "==> Waiting for readiness"
for _ in $(seq 1 30); do
	if $COMPOSE exec -T backend python -c "
import urllib.request, sys
try:
    r = urllib.request.urlopen('http://localhost:8000/api/v1/health/ready', timeout=3)
    sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; then
		echo "==> Ready. https://${SITE_ADDRESS}"
		exit 0
	fi
	sleep 2
done

echo "error: the backend did not become ready. Recent logs:" >&2
$COMPOSE logs --tail 40 backend >&2
exit 1
