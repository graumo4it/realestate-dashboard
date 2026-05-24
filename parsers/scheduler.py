"""
Планировщик запуска парсеров (для локального использования / VPS без GitHub Actions)

Расписание (ежемесячное, UTC):
  5-е  число, 08:00 — Субсидии ДОМ.РФ, первый прогон
               (данные за прошлый месяц считаются «завершёнными» через 5 дней после конца месяца)
  10-е число, 08:00 — CBR полный (включает второй прогон субсидий + все остальные показатели)
  10-е число, 09:00 — Rosstat/EMISS (обновляет 1.3 — зарплата, нужна для 5.10/5.11)
  20-е число, 10:00 — DomRF (после ручного добавления файлов в migration/domrf_data/)
               Включает calc_avg_apt_area (3.5), calc_sales_pace (5.9), calc_developer_activity (3.7), calc_demand_activity (5.3)
  20-е число, 10:30 — DomRF Web (автоматически скачивает xlsx с сайта ДОМ.РФ)
               После завершения — пересчёт 3.5 (calc_avg_apt_area), т.к. 3.3/3.4 обновились с сайта
               Затем — пересчёт 5.10 (calc_affordability) и 5.11 (calc_affordability_fcp),
               т.к. к этому моменту обновлены и 1.3 (Rosstat, 10-е), и матрица продаж (DomRF, 20-е),
               и apartments_area_2k (calc_avg_apt_area, только что)
"""
import logging
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
# migration/ нужен для импорта calc-скриптов
sys.path.insert(0, str(Path(__file__).parent.parent / "migration"))

from cbr import CBRParser, SubsidyOnlyParser
from domrf import DomRFParser
from domrf_web import DomRFWebParser
from rosstat import RosstatParser
import calc_avg_apt_area
import calc_affordability
import calc_affordability_fcp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="UTC")


@scheduler.scheduled_job("cron", day=5, hour=8, minute=0, id="subsidy_first")
def run_subsidy_first():
    """
    Первый прогон субсидий: запускается через 5 дней после окончания отч. месяца.
    Например, 5 июня — данные за май уже завершены и обновляются за последние 36 месяцев.
    """
    log.info("Starting Subsidy first pass (day 5)...")
    result = SubsidyOnlyParser().run()
    log.info(f"Subsidy first pass done: {result}")


@scheduler.scheduled_job("cron", day=10, hour=8, minute=0, id="cbr")
def run_cbr():
    """
    Полный CBR + второй прогон субсидий.
    Субсидии обновятся повторно (с возможно уточнёнными данными за последние 36 месяцев).
    """
    log.info("Starting CBR parser (full, including subsidy second pass)...")
    result = CBRParser().run()
    log.info(f"CBR done: {result}")


@scheduler.scheduled_job("cron", day=10, hour=9, minute=0, id="rosstat")
def run_rosstat():
    log.info("Starting Rosstat parser...")
    result = RosstatParser().run()
    log.info(f"Rosstat done: {result}")


@scheduler.scheduled_job("cron", day=20, hour=10, minute=0, id="domrf")
def run_domrf():
    log.info("Starting DomRF parser...")
    result = DomRFParser().run()
    log.info(f"DomRF done: {result}")


@scheduler.scheduled_job("cron", day=20, hour=10, minute=30, id="domrf_web")
def run_domrf_web():
    log.info("Starting DomRF Web parser...")
    result = DomRFWebParser().run()
    log.info(f"DomRF Web done: {result}")

    # 3.3 и 3.4 обновились — пересчитываем производный показатель 3.5
    log.info("Recalculating 3.5 (avg apartment area = 3.3 / 3.4)...")
    try:
        n = calc_avg_apt_area.main()
        log.info(f"calc_avg_apt_area done: {n} rows upserted")
    except Exception as e:
        log.error(f"calc_avg_apt_area failed: {e}", exc_info=True)

    # apartments_area_2k обновился + 1.3 актуален (Rosstat, 10-е) + матрица продаж (DomRF, 10:00)
    # → пересчитываем показатели доступности жилья
    log.info("Recalculating 5.10 (affordability: salary / price per sqm)...")
    try:
        calc_affordability.main()
        log.info("calc_affordability (5.10) done")
    except Exception as e:
        log.error(f"calc_affordability failed: {e}", exc_info=True)

    log.info("Recalculating 5.11 (affordability FCP: years to save for 2-room flat)...")
    try:
        calc_affordability_fcp.main()
        log.info("calc_affordability_fcp (5.11) done")
    except Exception as e:
        log.error(f"calc_affordability_fcp failed: {e}", exc_info=True)


if __name__ == "__main__":
    log.info(
        "Scheduler started "
        "(Subsidy first pass on 5th; CBR/Rosstat on 10th; DomRF/DomRF-Web on 20th). "
        "Press Ctrl+C to stop."
    )
    scheduler.start()
