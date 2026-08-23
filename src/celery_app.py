from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
import sys
from Celery.Config.celery_defination import celery_app


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# ============================================================
# Celery application
# ============================================================
celery_app.autodiscover_tasks(packages=["Celery.Tasks"])





