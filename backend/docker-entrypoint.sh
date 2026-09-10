#!/bin/sh
set -e

# Persistent volumes (e.g. Railway's) are mounted as root regardless of the image's
# USER directive, so anything volume-backed — the ML model registry — needs its
# ownership fixed on every boot, before dropping to the non-root app user.
if [ -d /app/models ]; then
  chown -R railcast:railcast /app/models 2>/dev/null || true
fi

exec gosu railcast "$@"
