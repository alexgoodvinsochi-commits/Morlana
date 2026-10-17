#!/usr/bin/env bash
# Put a branch on the development contour. Usage:
#   /opt/morlana-dev/ops/deploy-dev.sh [branch]
# With no argument it refreshes whatever branch the dev clone is already on.
# Production is deployed by deploy.sh and always from main; this one is the
# only place where a feature branch is allowed to run.
set -euo pipefail
cd /opt/morlana-dev
branch="${1:-$(git rev-parse --abbrev-ref HEAD)}"
git fetch --quiet origin
git checkout "$branch"
git pull --ff-only origin "$branch"
C="docker compose -p morlana-dev -f docker-compose.yml -f ops/docker-compose.dev.yml"
$C up -d --build
$C ps
