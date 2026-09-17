"""Workflow generation facade; service-owned models and resource snapshots are injected."""

from .pipeline.runner import WorkflowGenerator

__all__ = ["WorkflowGenerator"]
