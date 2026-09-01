# Interface web du Price Tracker V2.
# Build local le package ; le runtime expose le serveur uvicorn.

FROM python:3.12-slim AS build

WORKDIR /app
COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install ".[web]" .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PT_WEB_DIR=/app/web \
    HOST=127.0.0.1 \
    PORT=8030

WORKDIR /data

COPY --from=build /install /usr/local
COPY web /app/web

EXPOSE 8030

CMD ["sh", "-c", "python -m uvicorn price_tracker.web:create_app --factory --host $HOST --port $PORT"]