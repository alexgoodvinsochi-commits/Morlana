#!/usr/bin/env bash
# Daily dump of the live database, 14 days kept. Installed as /etc/cron.d/morlana-backup.
# Provider snapshots survive a dead disk; this survives a wrong DROP.
#
# Two things this script is careful about:
#   - `exec -T` reads stdin, so it gets /dev/null explicitly. Without it the
#     command eats whatever is feeding the script and the dump comes out short.
#   - The dump lands in a temp file and is only moved into place once it is
#     non-empty and starts with the PGDMP magic of a custom-format dump. An
#     empty file that looks like a backup is worse than no backup at all.
set -euo pipefail
dir=/var/backups/morlana
mkdir -p "$dir"
name="morlana_db_$(date +%Y%m%d_%H%M).dump"
tmp="$dir/.$name.part"
trap 'rm -f "$tmp"' EXIT
cd /opt/morlana
docker compose -f docker-compose.yml -f ops/docker-compose.prod.yml exec -T db \
    pg_dump -U user -Fc morlana_db < /dev/null > "$tmp"
[ -s "$tmp" ] || { echo "$(date -Is) FAIL: empty dump"; exit 1; }
head -c 5 "$tmp" | grep -q PGDMP || { echo "$(date -Is) FAIL: not a custom-format dump"; exit 1; }
mv "$tmp" "$dir/$name"
trap - EXIT
find "$dir" -name 'morlana_db_*.dump' -mtime +14 -delete
echo "$(date -Is) ok $name $(stat -c%s "$dir/$name") bytes"
