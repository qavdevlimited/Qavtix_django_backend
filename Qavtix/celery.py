import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Qavtix.settings")

app = Celery("Qavtix")

app.config_from_object("django.conf:settings", namespace="CELERY")


app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)

app.autodiscover_tasks()

