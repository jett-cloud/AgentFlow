# AgentFlow Studio API

This directory is the curated Python API snapshot for AgentFlow Studio. It depends on services and configuration such as PostgreSQL, Redis, storage, and model/provider settings; it is not a standalone production deployment.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- The services and configuration described in the repository [README](../README.md)

From the repository root, create a local configuration and install the API development dependencies:

```bash
cp api/.env.example api/.env
uv sync --project api --dev
```

Set strong local values in `api/.env` before starting services. Do not commit that file.

## Running locally

The API Docker entrypoint confirms the following application and Celery entrypoints. With the required services running and `api/.env` configured, run them from the repository root:

```bash
uv run --directory api python -m app
uv run --directory api celery -A celery_entrypoint.celery worker -P gevent -c 1 --loglevel INFO
```

For Compose-based services and the frontend workflow, follow the repository [README](../README.md). This curated snapshot does not include the upstream `web/` application or its development scripts.

## Tests

Run focused API tests from the repository root after dependencies and required test services are available:

```bash
uv run --directory api pytest tests/unit_tests/controllers/console/app/test_workflow_assist_api.py
```

Some integration tests require Docker-backed middleware or external services. See the root README for the snapshot's recorded verification status and limitations.
