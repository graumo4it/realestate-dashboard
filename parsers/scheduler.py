"""
Планировщик запуска парсеров (для локального использования / VPS без GitHub Actions)

Расписание (ежемесячное, UTC):
  5-е  число, 08:00 — subsidy_first: Субсидии ДОМ.РФ, первый прогон
               (данные за прошлый месяц считаются «завершёнными» через 5 дней после конца месяца)
  10-е число, 08:00 — day10: всё подряд без пауз
               1. CBR полный (включает второй прогон субсидий + все ипотечные показатели)
               2. Росреестр ДДУ (5.1 — квартально, scraper rosreestr.gov.ru)
               3. Rosstat/EMISS (1.3, 2.x, 4.4, 4.5) — без 1.2 (теперь из xlsx)
               4. fetch_income_rosstat (1.2 — xlsx с rosstat.gov.ru/folder/13397)
               5. calc_annual_companion (1.3.y = среднее Q1–Q4 из 1.3)
               6. calc_housing_per_capita (2.6/2.7/2.8 = ввод / население)
               7. migrate_population --all-years (1.1 — захардкожено, fedstat недоступен с облака)
               8. calc_housing_provision (2.10 = жилфонд[N] / население[N+1])
               9. calc_housing_need (5.12–5.15 по сценариям 33/38 кв. м)
  20-е число, 10:00 — day20: всё подряд без пауз
               1. DomRF (требует ручной загрузки файлов в migration/domrf_data/)
                  Включает: migrate_apartments, migrate_matrix_projects, migrate_sales_matrix,
                             migrate_under_construction_domrf, calc_sales_pace (5.9/5.9.ma12),
                             calc_sales_pace_mm (5.22/5.22.ma12), calc_developer_activity (3.7),
                             calc_demand_activity (5.3), calc_avg_apt_area (3.5)
               2. DomRF Web (автоматически скачивает xlsx с наш.дом.рф)
                  Обновляет: 3.1–3.4, 3.17–3.19
               3. calc_avg_apt_area (3.5) — повтор, т.к. 3.3/3.4 только что обновились с сайта
               4. calc_affordability (5.10 = зарплата / цена кв.м)
               5. calc_affordability_fcp (5.11 = лет копить на 2-комн. квартиру)
"""
import logging
import subprocess
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
# migration/ нужен для импорта calc-скриптов
sys.path.insert(0, str(Path(__file__).parent.parent / "migration"))

MIGRATION_DIR = Path(__file__).parent.parent / "migration"

from cbr import CBRParser, SubsidyOnlyParser
from domrf import DomRFParser
from domrf_web import DomRFWebParser
from rosstat import RosstatParser
import calc_avg_apt_area
import calc_affordability
import calc_affordability_fcp
import calc_housing_per_capita

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="UTC")


def _run_script(script_name: str, *args: str) -> int:
    """Запускает migration-скрипт как подпроцесс. Возвращает returncode."""
    cmd = [sys.executable, str(MIGRATION_DIR / script_name), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        log.info(result.stdout.strip())
    if result.stderr:
        log.warning(result.stderr.strip())
    if result.returncode != 0:
        log.error(f"{script_name} завершился с ошибкой: returncode={result.returncode}")
    return result.returncode


@scheduler.scheduled_job("cron", day=5, hour=8, minute=0, id="subsidy_first")
def run_subsidy_first():
    """
    Первый прогон субсидий: запускается через 5 дней после окончания отч. месяца.
    Например, 5 июня — данные за май уже завершены и обновляются за последние 36 месяцев.
    """
    log.info("=== subsidy_first (день 5) ===")
    result = SubsidyOnlyParser().run()
    log.info(f"Subsidy first pass done: {result}")


@scheduler.scheduled_job("cron", day=10, hour=8, minute=0, id="day10")
def run_day10():
    """
    Все источники 10-го числа — последовательно в одном джобе.
    CBR, Росреестр и Rosstat независимы по данным, но объединены для надёжности.
    """
    log.info("=== day10: CBR ===")
    result = CBRParser().run()
    log.info(f"CBR done: {result}")

    log.info("=== day10: Росреестр ДДУ (5.1) ===")
    _run_script("fetch_rosreestr_ddu.py")

    log.info("=== day10: Rosstat/EMISS (1.3, 2.x, 4.4, 4.5) ===")
    result = RosstatParser().run()
    log.info(f"Rosstat done: {result}")

    log.info("=== day10: fetch_income_rosstat (1.2) ===")
    _run_script("fetch_income_rosstat.py")

    log.info("=== day10: calc_annual_companion (1.3.y) ===")
    _run_script("calc_annual_companion.py")

    log.info("=== day10: calc_housing_per_capita (2.6/2.7/2.8) ===")
    try:
        n = calc_housing_per_capita.main()
        log.info(f"calc_housing_per_capita done: {n} rows upserted")
    except Exception as e:
        log.error(f"calc_housing_per_capita failed: {e}", exc_info=True)

    log.info("=== day10: население (1.1) ===")
    _run_script("migrate_population_1990_2010.py", "--all-years")

    # 2.9 обновился в шаге Rosstat, 1.1 — в шаге migrate_population
    log.info("=== day10: calc_housing_provision (2.10) ===")
    rc = _run_script("calc_housing_provision.py")
    if rc == 0:
        log.info("calc_housing_provision done")
    else:
        log.error(f"calc_housing_provision завершился с ошибкой, пропускаем calc_housing_need")

    # Зависит от 2.10 — запускаем только если шаг выше прошёл без ошибок
    if rc == 0:
        log.info("=== day10: calc_housing_need (5.12–5.15) ===")
        _run_script("calc_housing_need.py")

    log.info("=== day10: завершено ===")


@scheduler.scheduled_job("cron", day=20, hour=10, minute=0, id="day20")
def run_day20():
    """
    Все источники 20-го числа — последовательно в одном джобе.
    DomRF Web зависит от данных DomRF (матрица продаж нужна для calc_affordability),
    поэтому запускается строго после завершения DomRF.
    """
    log.info("=== day20: DomRF (файловый оркестратор) ===")
    result = DomRFParser().run()
    log.info(f"DomRF done: {result}")

    log.info("=== day20: DomRF Web (наш.дом.рф) ===")
    result = DomRFWebParser().run()
    log.info(f"DomRF Web done: {result}")

    # 3.3 и 3.4 только что обновились с сайта — пересчитываем 3.5
    log.info("=== day20: calc_avg_apt_area (3.5) ===")
    try:
        n = calc_avg_apt_area.main()
        log.info(f"calc_avg_apt_area done: {n} rows upserted")
    except Exception as e:
        log.error(f"calc_avg_apt_area failed: {e}", exc_info=True)

    # Теперь актуальны: 1.3 (Rosstat, 10-е) + матрица продаж (DomRF) + 3.5 (только что)
    log.info("=== day20: calc_affordability (5.10) ===")
    try:
        calc_affordability.main()
        log.info("calc_affordability (5.10) done")
    except Exception as e:
        log.error(f"calc_affordability failed: {e}", exc_info=True)

    log.info("=== day20: calc_affordability_fcp (5.11) ===")
    try:
        calc_affordability_fcp.main()
        log.info("calc_affordability_fcp (5.11) done")
    except Exception as e:
        log.error(f"calc_affordability_fcp failed: {e}", exc_info=True)

    log.info("=== day20: завершено ===")


if __name__ == "__main__":
    log.info(
        "Scheduler started. "
        "Запуск с caffeinate рекомендуется: caffeinate -s nohup python scheduler.py > /tmp/scheduler.log 2>&1 &"
        "  • 5-е,  08:00 UTC — subsidy_first"
        "  • 10-е, 08:00 UTC — day10 (CBR → Росреестр → Rosstat → calcs → 1.1)"
        "  • 20-е, 10:00 UTC — day20 (DomRF → DomRF Web → calcs)"
        "Press Ctrl+C to stop."
    )
    scheduler.start()
