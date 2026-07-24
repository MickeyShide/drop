from celery import Celery  # type: ignore[import-untyped]
from celery.signals import beat_init, worker_process_init  # type: ignore[import-untyped]

from drop.config import get_settings
from drop.logging import setup_logging
from drop.metrics import setup_metrics

settings = get_settings()

celery_app = Celery(
    "drop",
    broker=settings.rabbitmq_url,
    include=["drop.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_enable_remote_control=False,
    beat_schedule={
        "cleanup-expired-drops-every-5-minutes": {
            "task": "drop.cleanup_expired",
            "schedule": 300.0,
        },
        "publish-outbox-events-every-10-seconds": {
            "task": "drop.publish_outbox",
            "schedule": 10.0,
        },
    },
)


def _configure_observability(**_: object) -> None:
    setup_metrics()
    setup_logging()


worker_process_init.connect(_configure_observability)
beat_init.connect(_configure_observability)


def check_broker_connection(app: Celery | None = None) -> None:
    """Synchronously verify the RabbitMQ broker for the readiness endpoint."""
    connection = (app or celery_app).connection_for_read()
    try:
        connection.ensure_connection(max_retries=0)
    finally:
        connection.release()
