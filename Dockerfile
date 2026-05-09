###########
# BUILDER #
###########

FROM python:3.10-slim-bookworm AS builder

WORKDIR /usr/src/app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Build deps for any wheels that don't ship manylinux binaries.
RUN apt-get update \
  && apt-get -y install --no-install-recommends build-essential gcc \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
COPY ./requirements-api.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /usr/src/app/wheels -r requirements-api.txt


#########
# FINAL #
#########

FROM python:3.10-slim-bookworm

# Non-root user. System account, no home dir needed.
RUN addgroup --system app && adduser --system --group app

ENV APP_HOME=/app
RUN mkdir -p $APP_HOME
WORKDIR $APP_HOME

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV ENVIRONMENT prod
ENV PORT 8000

# Install + strip in one RUN. Cleaning in a later RUN doesn't shrink the
# image (Docker layers are immutable, deletes have to happen in the same
# layer that created the files). --no-compile skips byte-compilation so
# we're not creating .pyc files just to delete them.
COPY --from=builder /usr/src/app/wheels /wheels
COPY --from=builder /usr/src/app/requirements-api.txt .
RUN pip install --upgrade pip \
  && pip install --no-cache --no-compile /wheels/* \
  && pip install --no-cache --no-compile -r requirements-api.txt \
  && rm -rf /wheels \
  && find /usr/local/lib/python3.10/site-packages -depth \
       \( -type d \( -name '__pycache__' -o -name 'tests' -o -name 'test' \) \
          -o -name '*.pyc' -o -name '*.pyo' \) \
       -exec rm -rf '{}' + 2>/dev/null || true

# Only the artefacts the runtime needs.
COPY app ./app
COPY feast_repo ./feast_repo
COPY training/features.parquet ./training/features.parquet
COPY training/sample_request.json ./training/sample_request.json

RUN chown -R app:app $APP_HOME

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"

# gunicorn with uvicorn workers (FastAPI is ASGI).
CMD gunicorn --bind 0.0.0.0:$PORT app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 2 \
  --access-logfile - \
  --error-logfile - \
  --timeout 60 \
  --graceful-timeout 30
