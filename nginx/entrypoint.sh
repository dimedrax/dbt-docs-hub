#!/bin/sh
# Reborn DataOps Platform — nginx entrypoint with reload-on-flag watcher.
# The Metadata Indexer touches /var/run/nginx/reload.flag → we exec
# nginx -s reload.
set -eu

FLAG=/var/run/nginx/reload.flag
CONF_DIR=/etc/nginx/conf.d
mkdir -p "$(dirname "$FLAG")"

# Remove the stock nginx default.conf (server_name localhost) so the
# Indexer's portal.conf becomes the active server block.
rm -f "$CONF_DIR/default.conf"

# Wait until the Indexer has rendered at least one server block.
echo "[entrypoint] waiting for Indexer to render $CONF_DIR/portal.conf..."
while [ ! -f "$CONF_DIR/portal.conf" ]; do
    sleep 1
done
echo "[entrypoint] portal.conf detected, starting nginx"

flag_mtime() {
    if [ -f "$FLAG" ]; then
        stat -c %Y "$FLAG" 2>/dev/null || stat -f %m "$FLAG" 2>/dev/null || echo 0
    else
        echo 0
    fi
}

# Start nginx in background. nginx -s reload signals THIS master via SIGHUP;
# the master PID does not change, so $! stays valid for the whole lifetime.
nginx -g 'daemon off;' &
NGINX_PID=$!

trap 'kill -TERM $NGINX_PID 2>/dev/null; wait $NGINX_PID 2>/dev/null' TERM INT

# Seed the watcher with the flag's current mtime so a flag that already
# exists on the shared volume (after a container restart) is NOT treated
# as a fresh reload event.
LAST_MTIME=$(flag_mtime)

while kill -0 $NGINX_PID 2>/dev/null; do
    MTIME=$(flag_mtime)
    if [ "$MTIME" != "$LAST_MTIME" ]; then
        LAST_MTIME=$MTIME
        echo "[entrypoint] reload flag changed, reloading nginx..."
        nginx -s reload || echo "[entrypoint] nginx reload failed"
    fi
    sleep 2
done

echo "[entrypoint] nginx master exited"
