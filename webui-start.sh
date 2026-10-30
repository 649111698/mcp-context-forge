#!/bin/sh
# Fork (pexetech): start the web-ui BFF (new frontend) alongside the gateway.
#
# WEBUI_REDIS_URL is required (BFF session store). When it is empty the BFF
# stays down and the container runs as a plain gateway — the image is a safe
# drop-in replacement either way. The gateway is exec'd last so it stays the
# container's foreground process and receives the runtime signals.
set -u

if [ -n "${WEBUI_REDIS_URL:-}" ]; then
    echo "web-ui: starting BFF on :${WEBUI_PORT:-3000}" >&2
    (
        cd /opt/webui || exit 1
        # shellcheck disable=SC2086
        env \
            PORT="${WEBUI_PORT:-3000}" \
            COOKIE_SECURE="${WEBUI_COOKIE_SECURE:-false}" \
            REDIS_URL="${WEBUI_REDIS_URL}" \
            CONTEXTFORGE_URL="${WEBUI_CONTEXTFORGE_URL:-http://127.0.0.1:4444}" \
            ${WEBUI_PUBLIC_ORIGIN:+PUBLIC_ORIGIN="$WEBUI_PUBLIC_ORIGIN"} \
            ${WEBUI_TRUST_PROXY:+TRUST_PROXY="$WEBUI_TRUST_PROXY"} \
            node dist/index.js &
    )
else
    echo "web-ui: WEBUI_REDIS_URL empty — BFF not started, gateway only" >&2
fi

exec ./docker-entrypoint.sh
