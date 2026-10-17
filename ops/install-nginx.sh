#!/usr/bin/env bash
# Render a vhost for one contour from the shared template and put it live.
#
#   ops/install-nginx.sh morlana.ru      3000
#   ops/install-nginx.sh dev.morlana.ru  3001 --noindex
#
# The certificate must already exist: issue it first with
#   certbot certonly --webroot -w /var/www/html -d <domain>
# while a plain HTTP server block answers on port 80.
set -euo pipefail

domain="${1:?usage: install-nginx.sh <domain> <upstream-port> [--noindex]}"
port="${2:?usage: install-nginx.sh <domain> <upstream-port> [--noindex]}"
noindex="${3:-}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
site="/etc/nginx/sites-available/${domain}"
log="/var/log/nginx/${domain}-access.log"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed -e "s/DOMAIN/${domain}/g" -e "s/127.0.0.1:3000/127.0.0.1:${port}/g" "$here/nginx-morlana.conf" > "$tmp"

# The template carries a www alias, which only the apex domain has.
case "$domain" in
  *.*.*) sed -i "s/ www\.${domain}//g" "$tmp" ;;
esac

# One access log per contour, otherwise both land in the same file and there is
# no way to tell which site a request went to: the combined format omits the host.
sed -i "/^[[:space:]]*server_name /a\    access_log ${log};" "$tmp"

if [ "$noindex" = "--noindex" ]; then
    # A test contour has no business in search results. robots.txt asks crawlers
    # not to fetch; this tells them not to index even what they reach anyway.
    sed -i "s|    client_max_body_size 2m;|    add_header X-Robots-Tag \"noindex, nofollow\" always;\n    client_max_body_size 2m;|" "$tmp"
fi

sudo cp "$tmp" "$site"
sudo ln -sf "$site" "/etc/nginx/sites-enabled/${domain}"
sudo nginx -t
sudo systemctl reload nginx
# reload returns before the new workers accept connections.
sleep 3
echo "installed: ${domain} -> 127.0.0.1:${port}${noindex:+ (noindex)}"
