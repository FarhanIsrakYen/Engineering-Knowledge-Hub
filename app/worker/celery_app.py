from celery import Celery

from app.core.config import Settings, get_settings


def create_celery_app(settings: Settings) -> Celery:
    application = Celery(
        "engineering_knowledge_hub",
        broker=settings.redis_url,
        include=["app.worker.tasks"],
    )
    application.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_backend=None,
        task_ignore_result=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
    )
    return application


celery_app = create_celery_app(get_settings())
