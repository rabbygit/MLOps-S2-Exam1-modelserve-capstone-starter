# ============================================================================
# ModelServe — FastAPI Inference Service Dockerfile
# ============================================================================
# TODO: Implement a multi-stage Docker build.
#
# Requirements:
#   - Multi-stage build (at least two FROM statements)
#   - Final image must be under 800 MB
#   - Must run as a non-root user
#   - Must use a production WSGI/ASGI server (gunicorn with uvicorn workers)
#   - Must include a HEALTHCHECK directive
#   - Must copy only what's needed (use .dockerignore too)
#
# Suggested stages:
#   Stage 1 (builder):
#     - Start from python:3.10-slim
#     - Install build dependencies (gcc, etc.)
#     - Copy requirements.txt and install Python packages
#
#   Stage 2 (runtime):
#     - Start from python:3.10-slim (clean)
#     - Copy installed packages from builder stage
#     - Copy application code
#     - Create a non-root user and switch to it
#     - Expose the service port
#     - Set the healthcheck
#     - Define the CMD with gunicorn/uvicorn
# ============================================================================

FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY feast_repo ./feast_repo
COPY training/features.parquet ./training/features.parquet
COPY training/sample_request.json ./training/sample_request.json

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
