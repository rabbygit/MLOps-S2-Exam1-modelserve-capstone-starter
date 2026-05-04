###########
# BUILDER #
###########

# pull official base image
FROM python:3.10-slim-bookworm AS builder

# set working directory
WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# install system dependencies — only what's needed to compile any
# wheels that don't ship a manylinux binary
RUN apt-get update \
  && apt-get -y install --no-install-recommends build-essential gcc \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# install python dependencies
RUN pip install --upgrade pip
COPY ./requirements-api.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /usr/src/app/wheels -r requirements-api.txt


#########
# FINAL #
#########

# pull official base image
FROM python:3.10-slim-bookworm

# create the app user (system account; home dir not needed for runtime)
RUN addgroup --system app && adduser --system --group app

# application root
ENV APP_HOME=/app
RUN mkdir -p $APP_HOME
WORKDIR $APP_HOME

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV ENVIRONMENT prod
ENV PORT 8000

# install python dependencies + strip dev-only artefacts in a SINGLE
# RUN. Cleaning in a later RUN doesn't shrink the image — Docker layers
# are immutable, so the bytes have to be deleted in the same layer they
# were created in. --no-compile skips pip's byte-compilation step so we
# don't waste time generating .pyc files we're about to delete.
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

# add app — only the artefacts the runtime actually needs
COPY app ./app
COPY feast_repo ./feast_repo
COPY training/features.parquet ./training/features.parquet
COPY training/sample_request.json ./training/sample_request.json

# chown all the files to the app user
RUN chown -R app:app $APP_HOME

# change to the app user
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"

# run gunicorn with uvicorn workers (FastAPI is ASGI)
CMD gunicorn --bind 0.0.0.0:$PORT app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 2 \
  --access-logfile - \
  --error-logfile - \
  --timeout 60 \
  --graceful-timeout 30
