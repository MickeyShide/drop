#!/usr/bin/env sh
set -e

CMD="$1"

case "$CMD" in
  api)
    echo "Running database migrations (alembic upgrade head)..."
    alembic upgrade head
    echo "Starting FastAPI application server..."
    exec uvicorn drop.main:app --host 0.0.0.0 --port 8000
    ;;

  worker)
    echo "Starting Celery Worker..."
    exec celery -A drop.workers.celery_app:celery_app worker --loglevel=INFO
    ;;

  beat)
    echo "Starting Celery Beat scheduler..."
    exec celery -A drop.workers.celery_app:celery_app beat --loglevel=INFO
    ;;

  *)
    exec "$@"
    ;;
esac
