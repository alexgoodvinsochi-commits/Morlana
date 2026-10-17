#!/usr/bin/env bash
# Host configuration that lives outside the compose projects. Idempotent: safe to
# re-run after rebuilding the server or to repair drift. Run from either clone:
#   /opt/morlana/ops/install-host.sh
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Backups first: nothing below may stand in their way.
echo '15 4 * * * root /opt/morlana/ops/backup.sh >> /var/log/morlana-backup.log 2>&1' \
    | sudo tee /etc/cron.d/morlana-backup > /dev/null
sudo chmod 644 /etc/cron.d/morlana-backup
# Dumps hold people's private questions: root only, the ones already there too.
sudo install -d -m 700 /var/backups/morlana
sudo find /var/backups/morlana -type f -name '*.dump' -exec chmod 600 {} +

# Reload nginx after certbot renews a certificate (see certbot-reload-nginx.sh).
sudo install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
sudo install -m 755 "$here/certbot-reload-nginx.sh" /etc/letsencrypt/renewal-hooks/deploy/reload-nginx

# A catch-all server, so the bare IP and unknown names are dropped instead of
# landing on whichever site sorts first. It also answers ACME challenges for names
# without a vhost, which is the stock "default" site's job, so that site goes:
# two default_server blocks on one socket make nginx -t fail.
site=/etc/nginx/sites-available/default-drop
link=/etc/nginx/sites-enabled/default-drop
stock=/etc/nginx/sites-enabled/default
had_site=no; had_link=no; had_stock=no
if sudo test -f "$site"; then sudo cp "$site" "$work/site"; had_site=yes; fi
if sudo test -L "$link" || sudo test -e "$link"; then had_link=yes; fi
if sudo test -L "$stock" || sudo test -e "$stock"; then sudo mv "$stock" "$work/stock"; had_stock=yes; fi
sudo install -m 644 "$here/nginx-default.conf" "$site"
sudo ln -sf "$site" "$link"
if ! sudo nginx -t; then
    echo "nginx -t failed: putting the catch-all and the stock site back as they were" >&2
    if [ "$had_site" = yes ]; then sudo cp "$work/site" "$site"; else sudo rm -f "$site"; fi
    if [ "$had_link" = no ]; then sudo rm -f "$link"; fi
    if [ "$had_stock" = yes ]; then sudo mv "$work/stock" "$stock"; fi
    exit 1
fi
sudo systemctl reload nginx
# reload returns before the new workers accept connections.
sleep 3
echo "host configuration installed"
