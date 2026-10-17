#!/usr/bin/env bash
# Render a vhost for one contour from the shared template and put it live.
#
#   ops/install-nginx.sh morlana.ru      3000
#   ops/install-nginx.sh dev.morlana.ru  3001 --noindex
#
# The certificate must already exist: issue it first with
#   certbot certonly --webroot -w /var/www/html -d <domain>
# while a plain HTTP server block answers on port 80. Host-wide pieces (the
# catch-all server, the certbot reload hook) come from ops/install-host.sh.
set -euo pipefail

domain="${1:?usage: install-nginx.sh <domain> <upstream-port> [--noindex]}"
port="${2:?usage: install-nginx.sh <domain> <upstream-port> [--noindex]}"
noindex="${3:-}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
site="/etc/nginx/sites-available/${domain}"
link="/etc/nginx/sites-enabled/${domain}"
log="/var/log/nginx/${domain}-access.log"

tmp="$(mktemp)"
old="$(mktemp)"
trap 'rm -f "$tmp" "$old"' EXIT
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

# Install, test, and put the previous state back if nginx rejects it: a vhost
# left in place after a failed test would stop nginx at its next restart and
# take every site on the host down with it.
had_site=no; had_link=no
if sudo test -f "$site"; then sudo cp "$site" "$old"; had_site=yes; fi
if sudo test -L "$link" || sudo test -e "$link"; then had_link=yes; fi
sudo cp "$tmp" "$site"
sudo ln -sf "$site" "$link"
if ! sudo nginx -t; then
    echo "nginx -t failed: restoring the previous state of ${domain}" >&2
    if [ "$had_site" = yes ]; then sudo cp "$old" "$site"; else sudo rm -f "$site"; fi
    if [ "$had_link" = no ]; then sudo rm -f "$link"; fi
    exit 1
fi
sudo systemctl reload nginx
# reload returns before the new workers accept connections.
sleep 3
echo "installed: ${domain} -> 127.0.0.1:${port}${noindex:+ (noindex)}"
