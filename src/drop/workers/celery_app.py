from celery import Celery

from drop.config import get_settings


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