FROM python:3.12-alpine

RUN pip install --no-cache-dir "aiohttp>=3.9,<4"

WORKDIR /app
COPY bridge.py ./

ENTRYPOINT ["python3", "-u", "/app/bridge.py"]
