#!/usr/bin/env bash
# Put a branch on the development contour. Usage:
#   /opt/morlana-dev/ops/deploy-dev.sh [branch]
# With no argument it refreshes whatever branch the dev clone is already on.
# Production is deployed by deploy.sh and always from main; this is the only
# place where a feature branch is allowed to run.
set -euo pipefail
cd /opt/morlana-dev
branch="${1:-$(git rev-parse --abbrev-ref HEAD)}"
old_branch="$(git symbolic-ref -q --short HEAD || true)"
old_sha="$(git rev-parse HEAD)"
# refs/morlana/deployed marks what the containers actually run (see deploy.sh).
prev="$(git rev-parse --short --verify -q refs/morlana/deployed || git rev-parse --short HEAD)"
stage="dev containers still run ${prev}"
trap 'echo "dev deploy FAILED at: ${BASH_COMMAND} (${stage})" >&2' ERR

git fetch --quiet origin "$branch"
# The clone holds no work of its own, so it follows the remote exactly: a pull
# would refuse a branch that was rebased or force-pushed.
git checkout --quiet -B "$branch" "origin/$branch"
next="$(git rev-parse --short HEAD)"

C="docker compose -p morlana-dev -f docker-compose.yml -f ops/docker-compose.dev.yml"
# A branch cut before images were named after the compose project would build
# production's morlana-backend tag. Refuse it and put the clone back, so the next
# run does not start from that branch's own, unguarded copy of this script. The
# output is captured first: "config | grep -q" under pipefail can read a match as
# a failure when grep exits before compose has finished writing.
images="$($C config --images)"
if grep -qE '^morlana-(backend|frontend)(:|$)' <<< "$images"; then
    if [ -n "$old_branch" ]; then
        git checkout --quiet -B "$old_branch" "$old_sha"
    else
        git checkout --quiet --detach "$old_sha"
    fi
    echo "refusing: ${branch} would build a production image name; dev still runs ${prev}" >&2
    exit 1
fi

$C build
stage="dev is switching to ${next} and may be down"
$C up -d
git update-ref refs/morlana/deployed HEAD
$C ps
echo "dev now runs ${branch} @ ${next} (was ${prev})"
