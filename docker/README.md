# AgentFlow Docker Environment

This directory contains the Docker Compose configuration used by AgentFlow for local backend development.

## Start

From the repository root, generate the local environment file:

```bash
python docker/prepare_dev_env.py
```

Then start the backend and its required services:

```bash
docker compose -f docker/docker-compose.yaml -f docker/docker-compose.local.yaml up -d --build
```

The local override starts the AgentFlow API, worker, Agent backend, Plugin Daemon, PostgreSQL, Redis, vector database, Sandbox, and supporting services. The upstream Dify web and Nginx services are not enabled by default because AgentFlow uses the independent Vue frontend in `agent-flow-frontend/`.

See the [project Quick Start](../README.md#quick-start) for the complete local workflow.

## Configuration files

- `docker-compose.yaml` contains the upstream service definitions.
- `docker-compose.local.yaml` applies the AgentFlow local-development overrides.
- `.env.example` documents available environment variables.
- `.env` contains generated local values and is not committed.
- `prepare_dev_env.py` creates the local environment configuration.

Advanced upstream deployment options remain available in the Compose files, but they are outside the default AgentFlow development path.
