#!/bin/sh
# Optimal tarpit launch. One process, no Uvicorn Server header, no Uvicorn XFF rewrite.
# CHAKRAVYUH does its own trusted-peer X-Forwarded-For parsing.
set -eu
cd "$(dirname "$0")/.."
exec python main.py
