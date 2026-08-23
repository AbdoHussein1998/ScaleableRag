#src/Celery/Task/welcome_task.py

from Celery.Config.celery_defination import celery_app
from Dependencies.welcome_dependency import get_welcome_service
from asgiref.sync import async_to_sync
from Api.ApiConfiguration.api_settings import get_basic_settings


@celery_app.task(name="Welcome_Task", bind=True, max_retries=3)
def welcome_task(self):
    settings=get_basic_settings()
    try:
        # Safely bridge into async
        service = async_to_sync(get_welcome_service)()
        result = async_to_sync(service.run)()
        return {"result": result,
                "metadata":{
                    "AppName":settings.APP_NAME,
                    "AppVersion":settings.APP_VERSION
                }

                }
        
    except Exception as exc:
        # Standard Celery retry pattern
        raise self.retry(exc=exc, countdown=60)



