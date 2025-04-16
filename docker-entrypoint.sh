#!/bin/sh

chmod 600 /root/.ssh/id_ed25519 2>/dev/null || true

exec python -u /app/webhook-deployer.py
