#!/usr/bin/env sh
set -e

CMD="$1"

case "$CMD" in
  api)
    echo "Ensuring shared infrastructure resources..."
    python /app/docker/init-infra.py
    echo "Running database migrations (alembic upgrade head)..."
    alembic upgrade head
    echo "Starting FastAPI application server..."
    exec uvicorn drop.main:app --host 0.0.0.0 --port 8000
    ;;

  worker)
    if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
      mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
      rm -f "$PROMETHEUS_MULTIPROC_DIR"/*.db
    fi
    echo "Starting Celery Worker..."
    exec celery -A drop.workers.celery_app:celery_app worker --loglevel=INFO
    ;;

  beat)
    echo "Starting Celery Beat scheduler..."
    exec celery -A drop.workers.celery_app:celery_app beat --loglevel=INFO
    ;;

  metrics)
    exec python -m drop.workers.metrics_server
    ;;

  *)
    exec "$@"
    ;;
esac
