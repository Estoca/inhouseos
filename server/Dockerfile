FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --prefix=/install .

FROM python:3.12-slim

ARG GIT_COMMIT_SHA=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GIT_COMMIT_SHA=${GIT_COMMIT_SHA} \
    IHO_DATA_DIR=/data

# git is the storage format of every brain (LAB-51).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 iho \
    && mkdir /data && chown iho:iho /data

COPY --from=builder /install /usr/local

USER iho
WORKDIR /home/iho
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]

# One worker: brain snapshots and repo locks live in this process.
CMD ["uvicorn", "iho.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
