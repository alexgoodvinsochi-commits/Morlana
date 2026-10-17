#!/usr/bin/env bash
# Bring production up to the current main. Run as: /opt/morlana/ops/deploy.sh
#
# Everything that can fail runs while the old stack is still serving: the build,
# an import check of the new backend, a fresh dump and the migration. Compose's
# own "up" stops the serving backend before it starts migrate, so a migration that
# failed there would leave production down with nothing to fall back to.
set -euo pipefail
cd /opt/morlana
C="docker compose -f docker-compose.yml -f ops/docker-compose.prod.yml"

# refs/morlana/deployed marks what the containers actually run. HEAD cannot: a
# deploy that fails after the fast-forward leaves the checkout on the new commit
# while the old stack keeps serving.
prev="$(git rev-parse --short --verify -q refs/morlana/deployed || git rev-parse --short HEAD)"
stage="before the switch: production still runs ${prev}"
trap 'echo "deploy FAILED at: ${BASH_COMMAND} (${stage})" >&2' ERR

git fetch --quiet origin
git checkout --quiet main
git merge --ff-only --quiet origin/main
next="$(git rev-parse --short HEAD)"
echo "deploying ${prev} -> ${next}"

$C build
stage="before the switch: production still runs ${prev}, but the checkout and the image tags are already at ${next}; fix and re-run deploy.sh, do not run compose up by hand"
# Needs neither the database nor Redis: catches what only fails against this
# server's .env, persona file or registries, before anything is written.
$C run --rm -T --no-deps backend python -c "import main" < /dev/null
sudo ops/backup.sh | sudo tee -a /var/log/morlana-backup.log
# --no-deps: db is already up, and changes to its definition belong to "up".
$C run --rm -T --no-deps migrate < /dev/null
stage="the database is migrated for ${next}; ${prev} keeps serving but will refuse to boot if restarted, so finish the deploy"

$C up -d
git update-ref refs/morlana/deployed HEAD
stage="switched to ${next}, but it does not answer: production may be down; the dump above is from just before the switch"
# Through the frontend container, the way the host nginx reaches the app.
for _ in $(seq 1 30); do
    curl -fsS --max-time 3 http://127.0.0.1:3000/health > /dev/null 2>&1 && break
    sleep 2
done
curl -fsS --max-time 3 http://127.0.0.1:3000/health > /dev/null
$C ps
echo "production now runs ${next} (was ${prev})"
