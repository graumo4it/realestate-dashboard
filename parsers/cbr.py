"""
Парсер Банка России — ипотечная статистика
Источник: https://cbr.ru/statistics/bank_sector/mortgage/
"""
import io
import logging
import re
import sys
from datetime import date
from pathlib import Path

import requests
import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from base import BaseParser

log = logging.getLogger(__name__)

CBR_MORTGAGE_URL = "https://cbr.ru/statistics/bank_sector/mortgage/"

# Маппинг столбцов Excel → код показателя в БД
# Структура: {excel_sheet_keyword: {column_keyword: indicator_code}}
COLUMN_MAP = {
    "всего": {
        "количество": "6.1",
        "объём":      "6.2",
        "ставка":     "6.3",
        "срок":       "6.4",
        "размер":     "6.5",
        "платёж":     "6.6",
    },
    "первичный": {
        "количество": "6.7",
        "объём":      "6.8",
        "ставка":     "6.9",
        "срок":       "6.10",
        "размер":     "6.11",
        "платёж":     "6.12",
    },
    "вторичный": {
        "количество": "6.13",
        "объём":      "6.14",
        "ставка":     "6.15",
        "срок":       "6.16",
        "размер":     "6.17",
        "платёж":     "6.18",
    },
}

MONTH_MAP = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
    "май": 5, "июнь": 6, "июль": 7, "август": 8,
    "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}


class CBRParser(BaseParser):
    source_code = "cbr"

    def fetch_raw(self) -> bytes:
        """Скачивает страницу ЦБ, находит ссылку на последний Excel и скачивает его."""
        log.info("Fetching CBR mortgage page...")
        resp = requests.get(CBR_MORTGAGE_URL, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        # Ищем ссылку на .xlsx файл
        xlsx_link = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".xlsx" in href.lower() and "mortgage" in href.lower():
                xlsx_link = href if href.startswith("http") else f"https://cbr.ru{href}"
                break

        if not xlsx_link:
            # Fallback: берём первую ссылку на xlsx
            for a in soup.find_all("a", href=True):
                if ".xlsx" in a["href"].lower():
                    h = a["href"]
                    xlsx_link = h if h.startswith("http") else f"https://cbr.ru{h}"
                    break

        if not xlsx_link:
            raise ValueError("Could not find Excel file link on CBR page")

        log.info(f"Downloading: {xlsx_link}")
        r = requests.get(xlsx_link, timeout=60)
        r.raise_for_status()
        return r.content

    def parse(self, raw: bytes) -> list[dict]:
        records = []
        xf = pd.ExcelFile(io.BytesIO(raw))

        for sheet_name in xf.sheet_names:
            sheet_lower = sheet_name.lower()
            # Определяем категорию листа
            category_key = None
            for k in COLUMN_MAP:
                if k in sheet_lower:
                    category_key = k
                    break
            if category_key is None:
                continue

            df = pd.read_excel(xf, sheet_name=sheet_name, header=None)

            # Ищем строку заголовков (содержит год)
            header_row = None
            for idx, row in df.iterrows():
                vals = [str(v) for v in row if v is not None and str(v).strip()]
                years = [v for v in vals if re.match(r"20\d{2}", v)]
                if len(years) >= 2:
                    header_row = idx
                    break

            if header_row is None:
                continue

            headers = df.iloc[header_row].tolist()
            # Строка с типом показателя (может быть выше)
            metric_row = df.iloc[header_row - 1].tolist() if header_row > 0 else headers

            # Маппинг столбцов: col_index -> (year, indicator_code)
            col_map = {}
            for j, h in enumerate(headers):
                if j == 0:
                    continue
                try:
                    year = int(float(str(h)))
                    if 2015 <= year <= 2030:
                        # Определяем тип показателя из строки выше
                        metric_h = str(metric_row[j]).lower() if j < len(metric_row) else ""
                        for metric_kw, ind_code in COLUMN_MAP[category_key].items():
                            if metric_kw in metric_h:
                                col_map[j] = (year, ind_code)
                                break
                except (ValueError, TypeError):
                    pass

            # Данные: строки после заголовка
            for r_idx in range(header_row + 1, len(df)):
                row = df.iloc[r_idx]
                month_val = str(row.iloc[0]).strip().lower()
                if month_val not in MONTH_MAP:
                    continue
                month_num = MONTH_MAP[month_val]

                for col_j, (year, ind_code) in col_map.items():
                    v = row.iloc[col_j]
                    if v is None or str(v).strip() in ("", "х", "x", "-"):
                        continue
                    try:
                        value = float(str(v).replace(" ", "").replace(",", "."))
                    except (ValueError, TypeError):
                        continue

                    records.append({
                        "indicator_code": ind_code,
                        "period_date": date(year, month_num, 1),
                        "period_label": f"{row.iloc[0].strip()} {year}",
                        "value": value,
                    })

        log.info(f"CBR: parsed {len(records)} records")
        return records


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = CBRParser().run()
    print(result)
