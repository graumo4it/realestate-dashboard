"""
Планировщик запуска парсеров (для локального использования / VPS без GitHub Actions)
"""
import logging
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from cbr import CBRParser
from domrf import DomRFParser
from rosstat import RosstatParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="UTC")


@scheduler.scheduled_job("cron", hour=4, minute=0, id="domrf")
def run_domrf():
    log.info("Starting DomRF parser...")
    DomRFParser().run()


@scheduler.scheduled_job("cron", day_of_week="mon", hour=6, minute=0, id="cbr")
def run_cbr():
    log.info("Starting CBR parser...")
    CBRParser().run()


@scheduler.scheduled_job("cron", day_of_week="mon", hour=6, minute=30, id="rosstat")
def run_rosstat():
    log.info("Starting Rosstat parser...")
    RosstatParser().run()


if __name__ == "__main__":
    log.info("Scheduler started. Press Ctrl+C to stop.")
    scheduler.start()
