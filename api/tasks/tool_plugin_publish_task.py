"""Celery entry point for durable Studio tool-plugin publication."""

from celery import shared_task

from services.tool_plugin_generator.publish_job_runner import execute_publish_job


@shared_task(queue="plugin", acks_late=True, reject_on_worker_lost=True)
def tool_plugin_publish_task(job_id: str) -> None:
    execute_publish_job(job_id)
