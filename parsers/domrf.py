"""
Парсер ДОМ.РФ — строящееся жильё, цены, концентрация рынка
Источник: https://наш.дом.рф/opendata
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

DOMRF_OPENDATA_URL = "https://xn--d1aqf.xn--p1ai/api/opendata"

# Маппинг ключей API → коды показателей в БД
INDICATOR_MAP = {
    "housing_under_construction_sqm":   "3.1",
    "housing_under_construction_units":  "3.2",
    "housing_under_construction_houses": "3.3",
    "price_primary_sqm_ddu":            "4.1",
    "price_parking":                    "4.8",
    "demand_ddu_count":                 "5.8",
    "sales_rate":                       "5.9",
}


class DomRFParser(BaseParser):
    source_code = "domrf"

    def fetch_raw(self) -> list[dict]:
        """Запрашивает публичный API ДОМ.РФ."""
        all_data = []
        for key in INDICATOR_MAP:
            try:
                resp = requests.get(
                    DOMRF_OPENDATA_URL,
                    params={"indicator": key, "format": "json"},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    for item in data:
                        item["_indicator_key"] = key
                    all_data.extend(data)
                time.sleep(0.5)  # rate limit
            except Exception as e:
                log.warning(f"DomRF: failed to fetch {key}: {e}")
        return all_data

    def parse(self, raw: list[dict]) -> list[dict]:
        records = []
        for item in raw:
            key = item.get("_indicator_key")
            ind_code = INDICATOR_MAP.get(key)
            if not ind_code:
                continue

            # Стандартные поля API ДОМ.РФ
            period_str = item.get("period") or item.get("date") or item.get("period_date")
            value = item.get("value") or item.get("val")

            if not period_str or value is None:
                continue

            try:
                import re
                m = re.match(r"(\d{4})-(\d{2})", str(period_str))
                if m:
                    period_date = date(int(m.group(1)), int(m.group(2)), 1)
                else:
                    continue
                fval = float(str(value).replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                continue

            records.append({
                "indicator_code": ind_code,
                "period_date": period_date,
                "period_label": period_date.strftime("%B %Y"),
                "value": fval,
            })

        log.info(f"DomRF: parsed {len(records)} records")
        return records


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = DomRFParser().run()
    print(result)
