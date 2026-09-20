# Providers

This directory holds **optional workspace packages** inherited from Dify that plug into the AgentFlow API core. Providers implement the required interfaces and register themselves with the API core. The provider mechanism allows distributions to include only the integrations they need.

## Developing Providers

- [VDB Providers](vdb/README.md)

## Tests

Provider tests often live next to the package, e.g. `providers/<type>/<backend>/tests/unit_tests/`. Shared fixtures may live under `providers/` (e.g. `conftest.py`).

## Excluding Providers

In order to build with selected providers, use `--no-group vdb-all` and `--no-group trace-all` to disable default ones, then use `--group vdb-<provider>` and `--group trace-<provider>` to enable specific providers.
