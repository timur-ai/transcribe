FROM python:3.12-slim AS base

# Install FFmpeg and system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user
RUN useradd --create-home --shell /bin/bash botuser

WORKDIR /app

# Copy dependency files first for caching
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-editable

# Copy application code
COPY src/ ./src/
COPY alembic.ini ./

# Create tmp directory
RUN mkdir -p /tmp/transcribe && chown -R botuser:botuser /tmp/transcribe

# Switch to non-root user
USER botuser

# Run the bot
CMD ["uv", "run", "python", "-m", "src.main"]
