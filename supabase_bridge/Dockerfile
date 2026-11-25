# Base image pinned on digest (index digest of python:3.12-alpine, looked up 2026-11-23).
# How to bump: see "Updating the pinned versions" in DOCS.md.
FROM python:3.12-alpine@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89

RUN pip install --no-cache-dir "aiohttp==3.14.5"

WORKDIR /app
COPY bridge.py ./

ENTRYPOINT ["python3", "-u", "/app/bridge.py"]
