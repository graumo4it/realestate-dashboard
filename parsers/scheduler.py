"""
Планировщик запуска парсеров (для локального использования / VPS без GitHub Actions)

Расписание (UTC):

  Ежемесячно:
    1-е,  08:00 — day1_cbr_primary   : CBR ипотека 6.1–6.27 (02_02 + 02_03)
    5-е,  08:00 — day5_domrf_web     : DomRF Web (3.1–3.4, 3.17–3.19) + calc_avg_apt_area (3.5)
                                       retry каждые +5 дней пока нет новых данных 3.1
    7-е,  08:00 — day7_cbr_ihc      : CBR ИЖС + субсидии 6.36–6.87 (02_41 + субсидийный файл)
   20-е,  10:00 — day20_domrf       : DomRF оркестратор (5.x, 3.x, apartments)
                                       + calc_affordability (5.10) + calc_affordability_fcp (5.11)
                                       retry каждые +5 дней пока нет новых данных 5.9
   20-е,  11:00 — monthly_rosstat   : Rosstat ежемесячные 2.1/2.2/2.3 + calc_housing_per_capita (2.6-2.8)
                                       retry каждые +5 дней пока нет новых данных 2.1

  Ежеквартально (1 фев / 1 май / 1 авг / 1 ноя):
    08:00 — quarterly_rosstat        : Rosstat 1.3/4.4/4.5 + fetch_rosreestr_ddu (5.1)
                                       + fetch_income_rosstat (1.2 + 1.2.y)

  Ежегодно:
    1 фев,  08:30 — annual_companion      : calc_annual_companion (1.3.y)
                                            retry 1-е кажд. мес. пока нет новых данных 1.3.y
   15 мар,  08:00 — annual_population_dev : migrate_population (1.1)
                                            + calc_developer_activity (3.7)
                                            + calc_demand_activity (5.3)
                                            retry 15-е кажд. мес. пока нет новых данных 1.1
    5 июн,  08:00 — annual_housing_stats  : Rosstat 2.9/2.11/2.12/2.13
                                            → calc_housing_provision (2.10)
                                            → calc_housing_need (5.12–5.15)
                                            retry каждые +10 дней пока нет новых данных 2.9
"""
import functools
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg2
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "migration"))

MIGRATION_DIR = Path(__file__).parent.parent / "migration"

from cbr import CBRParser
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


# ─────────────────────────────────────────────────────────────────────────────
#  Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

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


def _get_db_conn():
    """Открывает новое соединение с БД, используя те же env-переменные что и парсеры."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def _has_new_data(indicator_codes: list[str], since_date: date) -> bool:
    """
    Возвращает True если в data_points есть хотя бы одна запись
    с period_date > since_date для любого из переданных кодов.
    """
    if not indicator_codes:
        return True
    conn = None
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM data_points dp
                JOIN indicators i ON dp.indicator_id = i.id
                WHERE i.code = ANY(%s) AND dp.period_date > %s
                """,
                (indicator_codes, since_date),
            )
            count = cur.fetchone()[0]
            return count > 0
    except Exception as e:
        log.error(f"_has_new_data failed ({indicator_codes}): {e}")
        return True  # fail open — не блокируем retry в случае ошибки БД
    finally:
        if conn:
            conn.close()


def _calc_retry_datetime(retry_days: int | None, retry_on_dom: int | None) -> datetime:
    """
    Вычисляет дату следующего retry.
      retry_days  — сдвиг от текущего момента на N дней
      retry_on_dom — следующее N-е число месяца (если сегодня уже >= N, берём следующий месяц)
    """
    now = datetime.utcnow()
    if retry_days is not None:
        return now + timedelta(days=retry_days)
    elif retry_on_dom is not None:
        today = now.date()
        if today.day < retry_on_dom:
            # В текущем месяце
            return datetime(today.year, today.month, retry_on_dom, 8, 0)
        else:
            # В следующем месяце
            if today.month == 12:
                return datetime(today.year + 1, 1, retry_on_dom, 8, 0)
            else:
                return datetime(today.year, today.month + 1, retry_on_dom, 8, 0)
    else:
        raise ValueError("Укажите retry_days или retry_on_dom")


def _run_job_with_retry(
    job_id: str,
    run_fn: "callable",
    check_codes: list[str],
    since_date: date,
    retry_days: int | None = None,
    retry_on_dom: int | None = None,
    max_retries: int = 12,
) -> None:
    """
    Запускает run_fn(), затем проверяет БД.
    Если новых данных (period_date > since_date) для check_codes не появилось
    и max_retries > 0 — добавляет одноразовый retry-job в scheduler.
    """
    log.info(f"[{job_id}] Запуск (retries_left={max_retries})…")
    try:
        run_fn()
    except Exception as e:
        log.error(f"[{job_id}] Ошибка выполнения: {e}", exc_info=True)

    if max_retries > 0 and not _has_new_data(check_codes, since_date):
        retry_dt = _calc_retry_datetime(retry_days, retry_on_dom)
        retry_id = f"{job_id}_retry_{retry_dt.strftime('%Y%m%d_%H%M')}"
        scheduler.add_job(
            functools.partial(
                _run_job_with_retry,
                job_id, run_fn, check_codes, since_date,
                retry_days, retry_on_dom, max_retries - 1,
            ),
            "date",
            run_date=retry_dt,
            id=retry_id,
            replace_existing=True,
            timezone="UTC",
        )
        log.info(f"[{job_id}] Новых данных нет → retry запланирован на {retry_dt} UTC (id={retry_id})")
    elif max_retries <= 0:
        log.warning(f"[{job_id}] Достигнут лимит retry — прекращаем попытки")
    else:
        log.info(f"[{job_id}] Новые данные подтверждены — retry не нужен")


def _prev_month_start() -> date:
    """Первый день предыдущего месяца (используется как since_date для ежемесячных job'ов)."""
    today = date.today()
    if today.month == 1:
        return date(today.year - 1, 12, 1)
    return date(today.year, today.month - 1, 1)


def _prev_year_start() -> date:
    """Первый день позапрошлого года (since_date для годовых job'ов)."""
    return date(date.today().year - 2, 1, 1)


# ─────────────────────────────────────────────────────────────────────────────
#  Функции-тела job'ов (вынесены для использования в retry-обёртке)
# ─────────────────────────────────────────────────────────────────────────────

def _do_day5_domrf_web():
    log.info("=== day5: DomRF Web (наш.дом.рф) ===")
    result = DomRFWebParser().run()
    log.info(f"DomRF Web done: {result}")

    log.info("=== day5: calc_avg_apt_area (3.5) ===")
    try:
        n = calc_avg_apt_area.main()
        log.info(f"calc_avg_apt_area done: {n} rows upserted")
    except Exception as e:
        log.error(f"calc_avg_apt_area failed: {e}", exc_info=True)


def _do_day20_domrf():
    log.info("=== day20: DomRF (файловый оркестратор) ===")
    result = DomRFParser().run()
    log.info(f"DomRF done: {result}")

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


def _do_monthly_rosstat():
    log.info("=== monthly_rosstat: Rosstat 2.1/2.2/2.3 ===")
    result = RosstatParser(codes=["2.1", "2.2", "2.3"]).run()
    log.info(f"Rosstat 2.x done: {result}")

    log.info("=== monthly_rosstat: calc_housing_per_capita (2.6/2.7/2.8) ===")
    try:
        n = calc_housing_per_capita.main()
        log.info(f"calc_housing_per_capita done: {n} rows upserted")
    except Exception as e:
        log.error(f"calc_housing_per_capita failed: {e}", exc_info=True)


def _do_annual_companion():
    log.info("=== annual_companion: fetch_income_rosstat (1.2.y) ===")
    _run_script("fetch_income_rosstat.py")

    log.info("=== annual_companion: calc_annual_companion (1.3.y) ===")
    _run_script("calc_annual_companion.py")


def _do_annual_population_dev():
    log.info("=== annual_population_dev: население (1.1) ===")
    _run_script("migrate_population_1990_2010.py", "--all-years")

    log.info("=== annual_population_dev: calc_developer_activity (3.7) ===")
    _run_script("calc_developer_activity.py")

    log.info("=== annual_population_dev: calc_demand_activity (5.3) ===")
    _run_script("calc_demand_activity.py")


def _do_annual_housing_stats():
    log.info("=== annual_housing_stats: Rosstat 2.9/2.11/2.12/2.13 ===")
    result = RosstatParser(codes=["2.9", "2.11", "2.12", "2.13"]).run()
    log.info(f"Rosstat annual housing done: {result}")

    log.info("=== annual_housing_stats: calc_housing_provision (2.10) ===")
    rc = _run_script("calc_housing_provision.py")
    if rc == 0:
        log.info("calc_housing_provision done")
        log.info("=== annual_housing_stats: calc_housing_need (5.12–5.15) ===")
        _run_script("calc_housing_need.py")
    else:
        log.error("calc_housing_provision завершился с ошибкой — пропускаем calc_housing_need")


# ─────────────────────────────────────────────────────────────────────────────
#  Scheduled jobs
# ─────────────────────────────────────────────────────────────────────────────

@scheduler.scheduled_job("cron", day=1, hour=8, minute=0, id="day1_cbr_primary")
def run_day1_cbr_primary():
    """
    1-е число, 08:00 UTC.
    CBR ипотека — базовые показатели 6.1–6.27 (02_02 + 02_03 + производные).
    Данные ЦБ РФ выходят строго в начале месяца — retry не нужен.
    """
    log.info("=== day1_cbr_primary (1-е число) ===")
    result = CBRParser(group="primary").run()
    log.info(f"CBR primary done: {result}")


@scheduler.scheduled_job("cron", day=5, hour=8, minute=0, id="day5_domrf_web")
def run_day5_domrf_web():
    """
    5-е число, 08:00 UTC.
    DomRF Web (наш.дом.рф) — показатели 3.1–3.4, 3.17–3.19.
    После — пересчёт 3.5 (calc_avg_apt_area).
    Retry: +5 дней если 3.1 не обновился.
    """
    log.info("=== day5_domrf_web (5-е число) ===")
    _run_job_with_retry(
        job_id="day5_domrf_web",
        run_fn=_do_day5_domrf_web,
        check_codes=["3.1"],
        since_date=_prev_month_start(),
        retry_days=5,
        max_retries=6,
    )


@scheduler.scheduled_job("cron", day=7, hour=8, minute=0, id="day7_cbr_ihc")
def run_day7_cbr_ihc():
    """
    7-е число, 08:00 UTC.
    CBR ИЖС + субсидии — показатели 6.36–6.87 (02_41 + субсидийный файл ДОМ.РФ).
    Данные ЦБ РФ стабильно доступны — retry не нужен.
    """
    log.info("=== day7_cbr_ihc (7-е число) ===")
    result = CBRParser(group="ihc").run()
    log.info(f"CBR IHC done: {result}")


@scheduler.scheduled_job("cron", day=20, hour=10, minute=0, id="day20_domrf")
def run_day20_domrf():
    """
    20-е число, 10:00 UTC.
    DomRF оркестратор (ручная загрузка файлов в migration/domrf_data/) — все domrf-показатели.
    После — calc_affordability (5.10) и calc_affordability_fcp (5.11).
    Retry: +5 дней если 5.9 не обновился.
    """
    log.info("=== day20_domrf (20-е число) ===")
    _run_job_with_retry(
        job_id="day20_domrf",
        run_fn=_do_day20_domrf,
        check_codes=["5.9"],
        since_date=_prev_month_start(),
        retry_days=5,
        max_retries=6,
    )


@scheduler.scheduled_job("cron", day=20, hour=11, minute=0, id="monthly_rosstat")
def run_monthly_rosstat():
    """
    20-е число, 11:00 UTC.
    Rosstat ежемесячные: 2.1 (ввод жилья), 2.2 (нарастающим итогом), 2.3 (ИЖС).
    После — calc_housing_per_capita (2.6/2.7/2.8 = ввод / население).
    Retry: +5 дней если 2.1 не обновился.
    """
    log.info("=== monthly_rosstat (20-е число) ===")
    _run_job_with_retry(
        job_id="monthly_rosstat",
        run_fn=_do_monthly_rosstat,
        check_codes=["2.1"],
        since_date=_prev_month_start(),
        retry_days=5,
        max_retries=6,
    )


@scheduler.scheduled_job("cron", month="2,5,8,11", day=1, hour=8, minute=0, id="quarterly_rosstat")
def run_quarterly_rosstat():
    """
    1 февраля / 1 мая / 1 августа / 1 ноября, 08:00 UTC.
    Rosstat квартальные: 1.3 (зарплата), 4.4/4.5 (ввод жилья квартальный/годовой).
    Росреестр: 5.1 (ДДУ регистрации).
    Доходы населения: fetch_income_rosstat (1.2 квартальный + 1.2.y годовой).
    Retry не нужен — данные гарантированно выходят в квартальные сроки.
    """
    log.info("=== quarterly_rosstat (1 фев/май/авг/ноя) ===")

    log.info("=== quarterly_rosstat: Rosstat 1.3/4.4/4.5 ===")
    codes = ["1.3", "4.4", "4.4.1", "4.4.2", "4.4.3", "4.5", "4.5.1", "4.5.2", "4.5.3", "4.5.4"]
    result = RosstatParser(codes=codes).run()
    log.info(f"Rosstat quarterly done: {result}")

    log.info("=== quarterly_rosstat: fetch_rosreestr_ddu (5.1) ===")
    _run_script("fetch_rosreestr_ddu.py")

    log.info("=== quarterly_rosstat: fetch_income_rosstat (1.2 + 1.2.y) ===")
    _run_script("fetch_income_rosstat.py")

    log.info("=== quarterly_rosstat: завершено ===")


@scheduler.scheduled_job("cron", month=2, day=1, hour=8, minute=30, id="annual_companion")
def run_annual_companion():
    """
    1 февраля, 08:30 UTC (после quarterly_rosstat на 08:00).
    Обновляет companion-показатели годовых рядов:
      1.2.y — годовые доходы населения (из fetch_income_rosstat)
      1.3.y — годовая зарплата (среднее Q1–Q4 из 1.3)
    Retry: 1-е число каждого следующего месяца пока 1.3.y не обновится.
    """
    log.info("=== annual_companion (1 февраля) ===")
    _run_job_with_retry(
        job_id="annual_companion",
        run_fn=_do_annual_companion,
        check_codes=["1.3.y"],
        since_date=_prev_year_start(),
        retry_on_dom=1,
        max_retries=12,
    )


@scheduler.scheduled_job("cron", month=3, day=15, hour=8, minute=0, id="annual_population_dev")
def run_annual_population_dev():
    """
    15 марта, 08:00 UTC.
    Ежегодные расчёты:
      1.1  — численность населения (migrate_population)
      3.7  — девелоперская активность (calc_developer_activity)
      5.3  — активность спроса (calc_demand_activity)
    Retry: 15-е число каждого следующего месяца пока 1.1 не обновится.
    """
    log.info("=== annual_population_dev (15 марта) ===")
    _run_job_with_retry(
        job_id="annual_population_dev",
        run_fn=_do_annual_population_dev,
        check_codes=["1.1"],
        since_date=_prev_year_start(),
        retry_on_dom=15,
        max_retries=12,
    )


@scheduler.scheduled_job("cron", day=25, hour=12, minute=0, id="monthly_status_update")
def run_monthly_status_update():
    """
    25-е число, 12:00 UTC.
    Обновляет столбцы «Актуальный период» и «Статус» в indicator_update_map.xlsx.
    Запускается после всех месячных парсеров (последний — 20-е число).
    """
    log.info("=== monthly_status_update (25-е число) ===")
    rc = _run_script("update_indicator_status.py")
    if rc == 0:
        log.info("indicator_update_map.xlsx обновлён")
    else:
        log.error("update_indicator_status.py завершился с ошибкой")


@scheduler.scheduled_job("cron", month=6, day=5, hour=8, minute=0, id="annual_housing_stats")
def run_annual_housing_stats():
    """
    5 июня, 08:00 UTC.
    Ежегодные жилищные показатели Росстат:
      2.9  — жилищный фонд (всего)
      2.11 — жилищный фонд (городской)
      2.12 — жилищный фонд (сельский)
      2.13 — жилищный фонд на 1 жителя
    После — последовательно:
      2.10 — обеспеченность жильём (calc_housing_provision)
      5.12–5.15 — потребность в жилье (calc_housing_need, только если 2.10 OK)
    Retry: +10 дней если 2.9 не обновился.
    Примечание: 2.13.ext исключён из расписания (данные устарели, нет источника).
    """
    log.info("=== annual_housing_stats (5 июня) ===")
    _run_job_with_retry(
        job_id="annual_housing_stats",
        run_fn=_do_annual_housing_stats,
        check_codes=["2.9"],
        since_date=_prev_year_start(),
        retry_days=10,
        max_retries=6,
    )


if __name__ == "__main__":
    log.info(
        "Scheduler started.\n"
        "Запуск с caffeinate рекомендуется: "
        "caffeinate -s nohup python scheduler.py > /tmp/scheduler.log 2>&1 &\n"
        "\nРасписание (UTC):\n"
        "  Ежемесячно:\n"
        "    1-е,  08:00 — day1_cbr_primary       (CBR 6.1–6.27)\n"
        "    5-е,  08:00 — day5_domrf_web          (DomRF Web 3.x + calc_avg_apt_area; retry +5д)\n"
        "    7-е,  08:00 — day7_cbr_ihc            (CBR ИЖС+субсидии 6.36–6.87)\n"
        "   20-е,  10:00 — day20_domrf             (DomRF оркестратор + affordability; retry +5д)\n"
        "   20-е,  11:00 — monthly_rosstat         (Rosstat 2.1-2.3 + housing_per_capita; retry +5д)\n"
        "   25-е,  12:00 — monthly_status_update   (обновляет indicator_update_map.xlsx)\n"
        "  Ежеквартально (1 фев/май/авг/ноя):\n"
        "    08:00 — quarterly_rosstat          (Rosstat 1.3/4.4/4.5 + Росреестр 5.1 + income 1.2)\n"
        "  Ежегодно:\n"
        "    1 фев,  08:30 — annual_companion       (1.2.y + 1.3.y; retry 1-е кажд. мес.)\n"
        "   15 мар,  08:00 — annual_population_dev  (1.1 + 3.7 + 5.3; retry 15-е кажд. мес.)\n"
        "    5 июн,  08:00 — annual_housing_stats   (2.9/2.10-2.13 + 5.12-5.15; retry +10д)\n"
        "\nPress Ctrl+C to stop."
    )
    scheduler.start()
