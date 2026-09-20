# AgentFlow Backend API

The AgentFlow backend provides workflow execution, Agent orchestration, datasets, MCP integration, tool management, and streaming APIs.

## Technology

- Python 3.12
- Flask and Celery
- SQLAlchemy and Pydantic
- `uv` for dependency management

## Run the backend

The supported local startup flow uses Docker Compose from the repository root. Follow the [project Quick Start](../README.md#quick-start) to generate the environment configuration and start the required services.

## Local development

Install the backend development dependencies:

```bash
cd api
uv sync --group dev
```

Run tests and code-quality checks:

```bash
uv run pytest tests/unit_tests
uv run ruff check .
uv run ruff format --check .
```

Integration tests may require PostgreSQL, Redis, a vector database, Sandbox, Plugin Daemon, or Agent Runtime services from the Docker environment.

## OpenAPI

Generate the OpenAPI specification with:

```bash
uv run dev/generate_swagger_specs.py --output-dir openapi
```
