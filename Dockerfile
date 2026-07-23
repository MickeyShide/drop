FROM python:3.13-slim AS base

# Install system dependencies & uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency files and install dependencies
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy application source code, migrations and configuration
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY docker/entrypoint.sh ./docker/entrypoint.sh

RUN sed -i 's/\r$//' ./docker/entrypoint.sh && chmod +x ./docker/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["api"]
