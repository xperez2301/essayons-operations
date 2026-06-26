#!/usr/bin/env bash
set -e
python -m gunicorn --bind=0.0.0.0:${PORT:-8000} --timeout 600 --workers ${WEB_CONCURRENCY:-2} app:app
