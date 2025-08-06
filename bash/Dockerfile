FROM python:3.9.6-alpine
# Dockerfile
FROM mongo:4.4

RUN apk update && apk add build-base && \
    adduser -D fastapi && \
    mkdir app && chown -R fastapi:fastapi /app

WORKDIR /app

USER fastapi
COPY requirements.txt requirements.txt
RUN python3 -m pip install --upgrade pip && pip install  --no-cache-dir -r requirements.txt
COPY . .
ENTRYPOINT [ "python", "main.py" ]