#!/usr/bin/env bash
# Bring the running stack up to the current main. Run as: /opt/morlana/ops/deploy.sh
set -euo pipefail
cd /opt/morlana
git fetch --quiet origin
git checkout main
git pull --ff-only
docker compose -f docker-compose.yml -f ops/docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f ops/docker-compose.prod.yml ps
