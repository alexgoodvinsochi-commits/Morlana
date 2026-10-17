#!/bin/sh
# certbot deploy hook, installed by ops/install-host.sh as
# /etc/letsencrypt/renewal-hooks/deploy/reload-nginx. certbot runs every executable
# there after a successful renewal. The certificates are issued with
# "certonly --webroot", which records no installer, so nothing else makes nginx
# load the renewed files: it would serve the old ones from memory until they expire.
nginx -t && systemctl reload nginx
