"""
Парсер Росстат — ввод жилья, жилищный фонд, цены
Источник: ЕМИСС / fedstat.ru API
"""
import logging
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).parent))
from base import BaseParser

log = logging.getLogger(__name__)

FEDSTAT_API = "https://www.fedstat.ru/api/data/{indicator_id}.json"

# ЕМИСС indicator_id -> код показателя в БД
EMISS_MAP = {
    "57783": "2.1",   # Ввод жилья — всего, тыс. кв. м
    "57784": "2.2",   # Ввод жилья — многоквартирные дома
    "57785": "2.3",   # Ввод жилья — ИЖС
    "31557": "4.4",   # Цены первичного рынка (Росстат)
    "31558": "4.5",   # Цены вторичного рынка (Росстат)
    "34059": "1.1",   # Население
    "30965": "1.2",   # Реальные доходы
    "57415": "1.3",   # Средняя зарплата
}

MONTH_NAMES_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}


class RosstatParser(BaseParser):
    source_code = "rosstat"

    def fetch_raw(self) -> dict:
        """Запрашивает ЕМИСС API для каждого показателя."""
        all_data: dict[str, list] = {}
        for emiss_id, ind_code in EMISS_MAP.items():
            try:
                url = FEDSTAT_API.format(indicator_id=emiss_id)
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                all_data[ind_code] = data
                log.info(f"Rosstat: fetched indicator {emiss_id} -> {ind_code}")
                time.sleep(1)  # ЕМИСС ограничивает частоту запросов
            except Exception as e:
                log.warning(f"Rosstat: failed to fetch {emiss_id}: {e}")
        return all_data

    def parse(self, raw: dict) -> list[dict]:
        records = []
        for ind_code, data in raw.items():
            if not isinstance(data, dict):
                continue
            # Структура ответа ЕМИСС: {"data": [{"period": "YYYY-MM", "value": N}, ...]}
            series = data.get("data") or data.get("values") or []
            if isinstance(series, dict):
                series = series.get("data") or []

            for item in series:
                period_str = item.get("period") or item.get("date") or ""
                value = item.get("value") or item.get("val")

                if not period_str or value is None:
                    continue

                try:
                    import re
                    m = re.match(r"(\d{4})[.-]?(\d{2})?", str(period_str))
                    if not m:
                        continue
                    year = int(m.group(1))
                    month = int(m.group(2)) if m.group(2) else 1
                    period_date = date(year, month, 1)
                    label = f"{MONTH_NAMES_RU[month]} {year}" if month != 1 else str(year)
                    fval = float(str(value).replace(",", ".").replace(" ", ""))
                except (ValueError, TypeError):
                    continue

                records.append({
                    "indicator_code": ind_code,
                    "period_date": period_date,
                    "period_label": label,
                    "value": fval,
                })

        log.info(f"Rosstat: parsed {len(records)} records")
        return records


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = RosstatParser().run()
    print(result)
