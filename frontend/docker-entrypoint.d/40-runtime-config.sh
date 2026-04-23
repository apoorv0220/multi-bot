#!/bin/sh
set -eu

TEMPLATE="/usr/share/nginx/html/runtime-config.template.js"
TARGET="/usr/share/nginx/html/runtime-config.js"

if [ -f "$TEMPLATE" ]; then
  WIDGET_BASE_URL="${WIDGET_BASE_URL:-}"
  PUBLIC_API_BASE_URL="${PUBLIC_API_BASE_URL:-}"
  export WIDGET_BASE_URL PUBLIC_API_BASE_URL
  envsubst '${WIDGET_BASE_URL} ${PUBLIC_API_BASE_URL}' < "$TEMPLATE" > "$TARGET"
fi
