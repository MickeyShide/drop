#!/usr/bin/env python
"""Ensure shared infrastructure resources exist for Drop."""
from __future__ import annotations

import asyncio
import os
import sys
from urllib.parse import urlparse

import asyncpg
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
import httpx


async def ensure_database() -> None:
    url = urlparse(os.environ["DATABASE_URL"])
    target_db = url.path.lstrip("/")
    if not target_db:
        print("DATABASE_URL missing database name", file=sys.stderr)
        sys.exit(1)

    admin_dsn = url._replace(path="/postgres", scheme="postgresql").geturl()
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target_db
        )
        if exists:
            print(f"PostgreSQL database '{target_db}' already exists")
            return
        await conn.execute(f'CREATE DATABASE "{target_db}"')
        print(f"PostgreSQL database '{target_db}' created")
    finally:
        await conn.close()


def ensure_rabbitmq_vhost() -> None:
    url = urlparse(os.environ["RABBITMQ_URL"])
    vhost = url.path.lstrip("/") or "/"
    user = url.username or "guest"
    password = url.password or "guest"
    host = url.hostname or "localhost"
    port = url.port or 15672

    auth = httpx.BasicAuth(user, password)
    base = f"http://{host}:{port}/api"

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{base}/vhosts/{vhost}", auth=auth)
        if resp.status_code == 200:
            print(f"RabbitMQ vhost '{vhost}' already exists")
            return
        if resp.status_code != 404:
            print(
                f"RabbitMQ check failed: {resp.status_code} {resp.text}",
                file=sys.stderr,
            )
            sys.exit(1)
        encoded_vhost = vhost.replace("/", "%2F")
        resp = client.put(f"{base}/vhosts/{encoded_vhost}", auth=auth)
        resp.raise_for_status()
        print(f"RabbitMQ vhost '{vhost}' created")


def ensure_minio_bucket() -> None:
    bucket = os.environ["S3_BUCKET"]
    endpoint = os.environ["S3_ENDPOINT"]
    access_key = os.environ["S3_ACCESS_KEY"]
    secret_key = os.environ["S3_SECRET_KEY"]
    region = os.environ.get("S3_REGION", "us-east-1")

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )
    try:
        client.head_bucket(Bucket=bucket)
        print(f"MinIO bucket '{bucket}' already exists")
        return
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
    client.create_bucket(Bucket=bucket)
    print(f"MinIO bucket '{bucket}' created")


async def main() -> None:
    await ensure_database()
    ensure_rabbitmq_vhost()
    ensure_minio_bucket()


if __name__ == "__main__":
    asyncio.run(main())