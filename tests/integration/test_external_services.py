import asyncio
import io
import time
import uuid
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import boto3
import pytest
from celery import Celery  # type: ignore[import-untyped]
from redis.asyncio import Redis
from testcontainers.core.container import DockerContainer  # type: ignore[import-untyped]

from drop.api.rate_limit import RateLimiter
from drop.config import get_settings
from drop.domain.exceptions import RateLimitExceededError
from drop.infrastructure.storage.s3 import S3Storage
from drop.workers.celery_app import check_broker_connection


def _wait_until(action: Callable[[], object], timeout_seconds: float = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            action()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError("External service did not become ready") from last_error


@pytest.mark.asyncio
async def test_rate_limit_lua_runs_against_real_redis() -> None:
    with DockerContainer("redis:7-alpine").with_exposed_ports(6379) as container:
        redis = Redis.from_url(
            f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0",
            decode_responses=True,
        )
        try:
            for _ in range(120):
                try:
                    await redis.ping()
                    break
                except Exception:
                    await asyncio.sleep(0.25)
            else:
                pytest.fail("Redis container did not become ready")
            await redis.flushdb()

            request = MagicMock()
            request.client = MagicMock(host="198.51.100.10")
            request.headers = {}
            request.path_params = {"public_id": "drop-123"}
            request.cookies = {}

            limiter = RateLimiter(name="real_redis", max_requests=1, window_seconds=60)
            with patch("drop.api.rate_limit.get_redis_client", return_value=redis):
                await limiter.check(request)
                with pytest.raises(RateLimitExceededError):
                    await limiter.check(request)
        finally:
            await redis.aclose()


def test_s3_storage_runs_against_real_minio() -> None:
    container = (
        DockerContainer("minio/minio:latest")
        .with_env("MINIO_ROOT_USER", "drop-test")
        .with_env("MINIO_ROOT_PASSWORD", "drop-test-password")
        .with_command("server /data --address :9000")
        .with_exposed_ports(9000)
    )
    with container:
        endpoint = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9000)}"
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id="drop-test",
            aws_secret_access_key="drop-test-password",
            region_name="us-east-1",
        )
        _wait_until(client.list_buckets)

        settings = get_settings()
        bucket = f"drop-test-{uuid.uuid4().hex}"
        with (
            patch.object(settings, "s3_endpoint", endpoint),
            patch.object(settings, "s3_access_key", "drop-test"),
            patch.object(settings, "s3_secret_key", "drop-test-password"),
            patch.object(settings, "s3_bucket", bucket),
        ):
            storage = S3Storage()
            storage.upload(
                io.BytesIO(b"real minio payload"), "drops/test/source", "text/plain"
            )

            assert storage.exists("drops/test/source") is True
            assert storage.get_object_metadata("drops/test/source") == (
                len(b"real minio payload"),
                "text/plain",
            )

            body, size, content_type = storage.get_object("drops/test/source")
            assert body.read() == b"real minio payload"
            assert size == len(b"real minio payload")
            assert content_type == "text/plain"

            storage.delete("drops/test/source")
            assert storage.exists("drops/test/source") is False


def test_rabbitmq_readiness_check_uses_real_broker() -> None:
    container = (
        DockerContainer("rabbitmq:3.13-alpine")
        .with_env("RABBITMQ_DEFAULT_USER", "drop-test")
        .with_env("RABBITMQ_DEFAULT_PASS", "drop-test-password")
        .with_exposed_ports(5672)
    )
    with container:
        broker_url = (
            "amqp://drop-test:drop-test-password@"
            f"{container.get_container_host_ip()}:{container.get_exposed_port(5672)}//"
        )
        app = Celery("rabbitmq-health-test", broker=broker_url)
        _wait_until(lambda: check_broker_connection(app))
