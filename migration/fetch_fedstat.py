"""
migration/fetch_fedstat.py

Загружает данные из fedstat.ru через POST /indicator/dataGrid.do
Формат payload точно соответствует тому что браузер отправляет на сайт.

ЗАПУСКАТЬ ЛОКАЛЬНО — fedstat блокирует облачные IP.

Использование:
  pip3 install requests psycopg2-binary python-dotenv
  python3 migration/fetch_fedstat.py

Требует .env в корне проекта: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import os, sys, math, time, re, logging
from datetime import date
from pathlib import Path

import requests
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
# Квартальные периоды fedstat → (месяц начала, метка)
# Формат 1: зарплата (57823) — накопительные периоды
# Формат 2: доходы (57039) — порядковые кварталы
CUMULATIVE_QUARTERS = {
    # Формат накопительный (зарплата)
    "январь-март":     (1,  "Q1"),
    "январь-июнь":     (4,  "Q2"),
    "январь-сентябрь": (7,  "Q3"),
    "январь-декабрь":  (10, "Q4"),
    # Формат порядковый (доходы)
    "i квартал":       (1,  "Q1"),
    "ii квартал":      (4,  "Q2"),
    "iii квартал":     (7,  "Q3"),
    "iv квартал":      (10, "Q4"),
    # Также попробуем числовые варианты
    "1 квартал":       (1,  "Q1"),
    "2 квартал":       (4,  "Q2"),
    "3 квартал":       (7,  "Q3"),
    "4 квартал":       (10, "Q4"),
}

# Отдельные месяцы (period_filter="true_monthly")
# Ключ — название месяца в нижнем регистре (dim33560 из fedstat)
# Значение — (номер месяца, заглавный вариант для period_label)
MONTH_NAMES = {
    "январь":   (1,  "Январь"),
    "февраль":  (2,  "Февраль"),
    "март":     (3,  "Март"),
    "апрель":   (4,  "Апрель"),
    "май":      (5,  "Май"),
    "июнь":     (6,  "Июнь"),
    "июль":     (7,  "Июль"),
    "август":   (8,  "Август"),
    "сентябрь": (9,  "Сентябрь"),
    "октябрь":  (10, "Октябрь"),
    "ноябрь":   (11, "Ноябрь"),
    "декабрь":  (12, "Декабрь"),
}


logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Конфиг индикаторов
#
# payload_base  — строка Form Data без параметра года (взята из DevTools)
# year_param    — шаблон параметра года (подставляем год в цикле)
# year_col_key  — ключ в results для поиска значения (dim{YEAR}_...)
# row_filter    — словарь dim-полей для фильтрации нужной строки из results
# years         — список лет для запроса
# divisor       — делитель значения (единицы → нужная единица)
# ─────────────────────────────────────────────────────────────────────────────

INDICATORS = [
    # ── 2.9 Жилфонд ──────────────────────────────────────────────────────────
    {
        "fedstat_id": "40454",
        "code":       "2.9",
        "name":       "Общая площадь жилых помещений (Жилфонд)",
        "unit":       "млн кв. м",
        "periodicity": "annual",
        "period_type": "point_in_time",
        "category":   "housing_stock",
        "source":     "rosstat",
        "divisor":    1000,
        "years":      list(range(2000, 2026)),
        "period_filter": None,   # None = берём первую строку по row_filter
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=58884&lineObjectIds=57831&lineObjectIds=58883"
            "&lineObjectIds=58824&lineObjectIds=58274"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_40454"
            "&selectedFilterIds=30611_950135"
            "&selectedFilterIds=33560_1558883"
            "&selectedFilterIds=57831_1688487"
            "&selectedFilterIds=58274_1707676"
            "&selectedFilterIds=58824_1751205"
            "&selectedFilterIds=58883_1784931"
            "&selectedFilterIds=58883_1784932"
            "&selectedFilterIds=58883_1784933"
            "&selectedFilterIds=58883_1784934"
            "&selectedFilterIds=58883_1784935"
            "&selectedFilterIds=58883_1784936"
            "&selectedFilterIds=58883_1784937"
            "&selectedFilterIds=58884_1784938"
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  {"dim58883": "Всего", "dim58274": "Всего"},
    },

    # ── 2.11 Прибыло жилфонда ────────────────────────────────────────────────
    {
        "fedstat_id": "40457",
        "code":       "2.11",
        "name":       "Площадь жилых помещений, введённых в действие (прибыло жилфонда)",
        "unit":       "млн кв. м",
        "periodicity": "annual",
        "period_type": "period",
        "category":   "housing_stock",
        "source":     "rosstat",
        "divisor":    1000,
        "years":      list(range(2000, 2026)),
        "period_filter": None,
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=57831&lineObjectIds=58274"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_40457"
            "&selectedFilterIds=30611_950135"
            "&selectedFilterIds=33560_1558883"
            "&selectedFilterIds=57831_1688487"
            "&selectedFilterIds=58274_1707676"
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  {"dim58274": "Всего"},
    },

    # ── 2.12 Выбыло жилфонда ─────────────────────────────────────────────────
    {
        "fedstat_id": "40456",
        "code":       "2.12",
        "name":       "Площадь жилых помещений, выбывших из жилищного фонда",
        "unit":       "млн кв. м",
        "periodicity": "annual",
        "period_type": "period",
        "category":   "housing_stock",
        "source":     "rosstat",
        "divisor":    1000,
        "years":      list(range(2000, 2026)),
        "period_filter": None,
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=57831&lineObjectIds=58274"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_40456"
            "&selectedFilterIds=30611_950135"
            "&selectedFilterIds=33560_1558883"
            "&selectedFilterIds=57831_1688487"
            "&selectedFilterIds=58274_1707676"
            "&selectedFilterIds=58274_1710521"
            "&selectedFilterIds=58274_1759500"
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  {"dim58274": "Всего"},
    },

    # ── 2.13.ext Доля ветхого жилья ──────────────────────────────────────────
    {
        "fedstat_id": "40458",
        "code":       "2.13.ext",
        "name":       "Удельный вес ветхого и аварийного жилищного фонда",
        "unit":       "%",
        "periodicity": "annual",
        "period_type": "point_in_time",
        "category":   "housing_stock",
        "source":     "rosstat",
        "divisor":    1,
        "years":      list(range(2000, 2026)),
        "period_filter": None,
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=57831&lineObjectIds=58824&lineObjectIds=58274"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_40458"
            "&selectedFilterIds=30611_950473"
            "&selectedFilterIds=33560_1558883"
            "&selectedFilterIds=57831_1688487"
            "&selectedFilterIds=57831_1688488"
            "&selectedFilterIds=57831_1688507"
            "&selectedFilterIds=57831_1688520"
            "&selectedFilterIds=57831_1688521"
            "&selectedFilterIds=57831_1688528"
            "&selectedFilterIds=57831_1688536"
            "&selectedFilterIds=57831_1688552"
            "&selectedFilterIds=57831_1688560"
            "&selectedFilterIds=57831_1688577"
            "&selectedFilterIds=57831_1692937"
            "&selectedFilterIds=57831_1697988"
            "&selectedFilterIds=58274_1707676"
            "&selectedFilterIds=58824_1751203"
            "&selectedFilterIds=58824_1751204"
            "&selectedFilterIds=58824_1751205"
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  {"dim57831": "Российская Федерация", "dim58824": "Весь жилищный фонд", "dim58274": "Всего"},
    },

    # ── 1.3 Зарплата месячная (fedstat 57823) ────────────────────────────────
    # Берём каждый месяц отдельно: row_filter dim57831="Российская Федерация"
    # и dim33560 = название месяца (не накопительный период)
    {
        "fedstat_id": "57823",
        "code":       "1.3",
        "name":       "Среднемесячная номинальная начисленная заработная плата работников организаций",
        "unit":       "руб.",
        "periodicity": "quarterly",
        "period_type": "period",
        "category":   "macro",
        "source":     "rosstat",
        "divisor":    1,
        "years":      list(range(2017, 2027)),
        # Росстат публикует зарплату как накопительные кварталы:
        # «янв-мар», «янв-июн», «янв-сен», «янв-дек» из dim33560.
        # Хранятся на 1-е число начального месяца квартала (CUMULATIVE_QUARTERS).
        "period_filter": "monthly",   # читает CUMULATIVE_QUARTERS из dim33560
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=57940"
            "&lineObjectIds=57940&lineObjectIds=57831&lineObjectIds=33560"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_57823"
            "&selectedFilterIds=30611_950351"
            "&selectedFilterIds=33560_1540228"
            "&selectedFilterIds=33560_1540229"
            "&selectedFilterIds=33560_1540230"
            "&selectedFilterIds=33560_1540233"
            "&selectedFilterIds=33560_1540234"
            "&selectedFilterIds=33560_1540235"
            "&selectedFilterIds=33560_1540236"
            "&selectedFilterIds=33560_1540272"
            "&selectedFilterIds=33560_1540273"
            "&selectedFilterIds=33560_1540276"
            "&selectedFilterIds=33560_1540282"
            "&selectedFilterIds=33560_1540283"
            "&selectedFilterIds=33560_1540284"
            "&selectedFilterIds=33560_1540285"
            "&selectedFilterIds=33560_1540286"
            "&selectedFilterIds=33560_1540287"
            "&selectedFilterIds=33560_1540288"
            "&selectedFilterIds=33560_1540289"
            "&selectedFilterIds=33560_1540290"
            "&selectedFilterIds=33560_1540291"
            "&selectedFilterIds=33560_1540292"
            "&selectedFilterIds=33560_1540293"
            "&selectedFilterIds=33560_1540294"
            "&selectedFilterIds=57831_1688487"
            "&selectedFilterIds=57831_1849012"
            "&selectedFilterIds=57940_1692933"
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        # С середины 2025 fedstat переключил dim57831 на «Российская Федерация
        # без учета новых субъектов». Каждый period (dim33560) встречается ровно
        # один раз → фильтруем только по виду деятельности (dim57940).
        "row_filter":  {"dim57940": "Всего по обследуемым видам экономической деятельности"},
    },

    # ── 2.3 Ввод жилья МЖС / организации (fedstat 34118) ────────────────────
    # dim58389=1836599 — «Жилые здания» — только организации (МЖС).
    # ⚠️ В fedstat «Жилые здания» = организации, НЕ grand total.
    #    Grand total «Жилые здания, жилые помещения в нежилых зданиях
    #    и жилые дома, построенные населением» вычисляется ниже: 2.1 = 2.3 + 2.2
    # period_filter=true_monthly — 12 отдельных строк (январь..декабрь) на год
    # row_filter_by_year: 2023+ — «без учёта новых субъектов»
    {
        "fedstat_id": "34118",
        "code":       "2.3",
        "name":       "Объём ввода жилья МЖС (организации)",
        "unit":       "тыс. кв. м",
        "periodicity": "monthly",
        "period_type": "period",
        "category":   "supply_volume",
        "source":     "rosstat",
        "divisor":    1,
        "years":      list(range(2012, 2027)),
        "period_filter": "true_monthly",
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=57831&lineObjectIds=58389"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_34118"
            "&selectedFilterIds=30611_950292"
            "&selectedFilterIds=33560_1540283"   # январь
            "&selectedFilterIds=33560_1540282"   # февраль
            "&selectedFilterIds=33560_1540236"   # март
            "&selectedFilterIds=33560_1540229"   # апрель
            "&selectedFilterIds=33560_1540235"   # май
            "&selectedFilterIds=33560_1540234"   # июнь
            "&selectedFilterIds=33560_1540233"   # июль
            "&selectedFilterIds=33560_1540228"   # август
            "&selectedFilterIds=33560_1540276"   # сентябрь
            "&selectedFilterIds=33560_1540273"   # октябрь
            "&selectedFilterIds=33560_1540272"   # ноябрь
            "&selectedFilterIds=33560_1540230"   # декабрь
            "&selectedFilterIds=57831_1688487"   # Российская Федерация
            "&selectedFilterIds=57831_1849012"   # РФ без учёта новых субъектов (с 01.01.2023)
            "&selectedFilterIds=58389_1836599"   # Жилые здания (всего)
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  None,
        "row_filter_by_year": {
            "default": {"dim57831": "Российская Федерация"},
            2023: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2024: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2025: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2026: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
        },
    },

    # ── 2.2 Ввод жилья ИЖС (fedstat 34118) ──────────────────────────────────
    # Тот же endpoint, другой dim58389: 1754556 = «Жилые дома, построенные населением»
    # 2.1 (Всего) рассчитывается SQL-скриптом: 2.1 = 2.3 + 2.2
    {
        "fedstat_id": "34118",
        "code":       "2.2",
        "name":       "Объем ввода жилья, построенного населением (ИЖС), тыс. кв. м",
        "unit":       "тыс. кв. м",
        "periodicity": "monthly",
        "period_type": "period",
        "category":   "supply_volume",
        "source":     "rosstat",
        "divisor":    1,
        "years":      list(range(2012, 2027)),
        "period_filter": "true_monthly",
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=57831&lineObjectIds=58389"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_34118"
            "&selectedFilterIds=30611_950292"
            "&selectedFilterIds=33560_1540283"   # январь
            "&selectedFilterIds=33560_1540282"   # февраль
            "&selectedFilterIds=33560_1540236"   # март
            "&selectedFilterIds=33560_1540229"   # апрель
            "&selectedFilterIds=33560_1540235"   # май
            "&selectedFilterIds=33560_1540234"   # июнь
            "&selectedFilterIds=33560_1540233"   # июль
            "&selectedFilterIds=33560_1540228"   # август
            "&selectedFilterIds=33560_1540276"   # сентябрь
            "&selectedFilterIds=33560_1540273"   # октябрь
            "&selectedFilterIds=33560_1540272"   # ноябрь
            "&selectedFilterIds=33560_1540230"   # декабрь
            "&selectedFilterIds=57831_1688487"   # Российская Федерация
            "&selectedFilterIds=57831_1849012"   # РФ без учёта новых субъектов (с 01.01.2023)
            "&selectedFilterIds=58389_1754556"   # Жилые дома, построенные населением (ИЖС)
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  None,
        "row_filter_by_year": {
            "default": {"dim57831": "Российская Федерация"},
            2023: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2024: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2025: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2026: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
        },
    },

    # ── 4.4 Цены первичного рынка (fedstat 31452) ────────────────────────────
    # dim63148=1855614 — «Первичный рынок жилья»; dim58849=1752264 — «Все типы квартир»
    # period_filter=monthly: читает строки с «I квартал» … «IV квартал» из dim33560
    {
        "fedstat_id": "31452",
        "code":       "4.4",
        "name":       "Средняя стоимость сделок с жильем (Росстат)",
        "unit":       "руб. / кв. м",
        "periodicity": "quarterly",
        "period_type": "period",
        "category":   "prices",
        "source":     "rosstat",
        "divisor":    1,
        "years":      list(range(2000, 2027)),
        "period_filter": "monthly",   # CUMULATIVE_QUARTERS включает «i квартал» и т.п.
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=57831&lineObjectIds=58849&lineObjectIds=63148"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_31452"
            "&selectedFilterIds=30611_950351"
            "&selectedFilterIds=33560_1540222"   # I квартал
            "&selectedFilterIds=33560_1540224"   # II квартал
            "&selectedFilterIds=33560_1540226"   # III квартал
            "&selectedFilterIds=33560_1540227"   # IV квартал
            "&selectedFilterIds=57831_1688487"   # Российская Федерация
            "&selectedFilterIds=57831_1849012"   # РФ без учёта новых субъектов
            "&selectedFilterIds=58849_1752264"   # Все типы квартир
            "&selectedFilterIds=63148_1855614"   # Первичный рынок жилья
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  None,
        "row_filter_by_year": {
            "default": {"dim57831": "Российская Федерация"},
            2023: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2024: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2025: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2026: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
        },
    },

    # ── 4.5 Цены вторичного рынка (fedstat 31452) ────────────────────────────
    # Тот же endpoint, другой dim63148: 1855615 = «Вторичный рынок жилья»
    {
        "fedstat_id": "31452",
        "code":       "4.5",
        "name":       "Средняя стоимость 1 кв. м на вторичном рынке (все типы квартир)",
        "unit":       "руб. / кв. м",
        "periodicity": "quarterly",
        "period_type": "period",
        "category":   "prices",
        "source":     "rosstat",
        "divisor":    1,
        "years":      list(range(2000, 2027)),
        "period_filter": "monthly",
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=57831&lineObjectIds=58849&lineObjectIds=63148"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_31452"
            "&selectedFilterIds=30611_950351"
            "&selectedFilterIds=33560_1540222"   # I квартал
            "&selectedFilterIds=33560_1540224"   # II квартал
            "&selectedFilterIds=33560_1540226"   # III квартал
            "&selectedFilterIds=33560_1540227"   # IV квартал
            "&selectedFilterIds=57831_1688487"   # Российская Федерация
            "&selectedFilterIds=57831_1849012"   # РФ без учёта новых субъектов
            "&selectedFilterIds=58849_1752264"   # Все типы квартир
            "&selectedFilterIds=63148_1855615"   # Вторичный рынок жилья
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  None,
        "row_filter_by_year": {
            "default": {"dim57831": "Российская Федерация"},
            2023: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2024: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2025: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2026: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
        },
    },

    # ── 4.4.1–4.4.3  Первичный рынок по типам квартир (fedstat 31452) ─────────
    # dim63148=1855614 — «Первичный рынок жилья»
    # dim58849: 1752262=средние/типовые, 1752261=улучшенные, 1752260=элитные
    *[
        {
            "fedstat_id": "31452",
            "code":        code,
            "name":        name,
            "unit":        "руб. / кв. м",
            "periodicity": "quarterly",
            "period_type": "period",
            "category":    "prices",
            "source":      "rosstat",
            "divisor":     1,
            "years":       list(range(2000, 2027)),
            "period_filter": "monthly",
            "payload_base": (
                "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
                "&lineObjectIds=57831&lineObjectIds=58849&lineObjectIds=63148"
                "&columnObjectIds=3"
                "&selectedFilterIds=0_31452"
                "&selectedFilterIds=30611_950351"
                "&selectedFilterIds=33560_1540222"
                "&selectedFilterIds=33560_1540224"
                "&selectedFilterIds=33560_1540226"
                "&selectedFilterIds=33560_1540227"
                "&selectedFilterIds=57831_1688487"
                "&selectedFilterIds=57831_1849012"
                f"&selectedFilterIds=58849_{apt_id}"
                "&selectedFilterIds=63148_1855614"   # Первичный рынок
            ),
            "year_param":  "selectedFilterIds=3_{year}",
            "row_filter":  None,
            "row_filter_by_year": {
                "default": {"dim57831": "Российская Федерация"},
                2023: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
                2024: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
                2025: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
                2026: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            },
        }
        for code, name, apt_id in [
            ("4.4.1", "Средняя стоимость 1 кв. м на первичном рынке — квартиры среднего качества (типовые)", "1752262"),
            ("4.4.2", "Средняя стоимость 1 кв. м на первичном рынке — квартиры улучшенного качества",        "1752261"),
            ("4.4.3", "Средняя стоимость 1 кв. м на первичном рынке — элитные квартиры",                    "1752260"),
        ]
    ],

    # ── 4.5.1–4.5.4  Вторичный рынок по типам квартир (fedstat 31452) ─────────
    # dim63148=1855615 — «Вторичный рынок жилья»
    # dim58849: 1752263=низкого качества, 1752262=средние/типовые,
    #           1752261=улучшенные, 1752260=элитные
    *[
        {
            "fedstat_id": "31452",
            "code":        code,
            "name":        name,
            "unit":        "руб. / кв. м",
            "periodicity": "quarterly",
            "period_type": "period",
            "category":    "prices",
            "source":      "rosstat",
            "divisor":     1,
            "years":       list(range(2000, 2027)),
            "period_filter": "monthly",
            "payload_base": (
                "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
                "&lineObjectIds=57831&lineObjectIds=58849&lineObjectIds=63148"
                "&columnObjectIds=3"
                "&selectedFilterIds=0_31452"
                "&selectedFilterIds=30611_950351"
                "&selectedFilterIds=33560_1540222"
                "&selectedFilterIds=33560_1540224"
                "&selectedFilterIds=33560_1540226"
                "&selectedFilterIds=33560_1540227"
                "&selectedFilterIds=57831_1688487"
                "&selectedFilterIds=57831_1849012"
                f"&selectedFilterIds=58849_{apt_id}"
                "&selectedFilterIds=63148_1855615"   # Вторичный рынок
            ),
            "year_param":  "selectedFilterIds=3_{year}",
            "row_filter":  None,
            "row_filter_by_year": {
                "default": {"dim57831": "Российская Федерация"},
                2023: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
                2024: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
                2025: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
                2026: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            },
        }
        for code, name, apt_id in [
            ("4.5.1", "Средняя стоимость 1 кв. м на вторичном рынке — квартиры низкого качества",            "1752263"),
            ("4.5.2", "Средняя стоимость 1 кв. м на вторичном рынке — квартиры среднего качества (типовые)", "1752262"),
            ("4.5.3", "Средняя стоимость 1 кв. м на вторичном рынке — квартиры улучшенного качества",        "1752261"),
            ("4.5.4", "Средняя стоимость 1 кв. м на вторичном рынке — элитные квартиры",                    "1752260"),
        ]
    ],

    # ── 2.13 Благоустройство жилфонда (fedstat 43507) ────────────────────────
    # Годовой показатель; decimal-разделитель — точка (обрабатывается extract_value)
    # dim58274=1707676 — «Всего» (без разбивки город/село)
    # Для этого индикатора «без новых субъектов» в dim57831 нет → только РФ
    {
        "fedstat_id": "43507",
        "code":       "2.13",
        "name":       "Доля жилфонда, обеспеченного всеми видами благоустройства",
        "unit":       "%",
        "periodicity": "annual",
        "period_type": "point_in_time",
        "category":   "housing_stock",
        "source":     "rosstat",
        "divisor":    1,
        "years":      list(range(2013, 2026)),
        "period_filter": None,
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=57831&lineObjectIds=58274"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_43507"
            "&selectedFilterIds=30611_950473"
            "&selectedFilterIds=33560_1558883"   # значение показателя за год
            "&selectedFilterIds=57831_1688487"   # Российская Федерация
            "&selectedFilterIds=58274_1707676"   # Всего
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  {"dim57831": "Российская Федерация", "dim58274": "Всего"},
    },

    # ── 5.1 Кол-во ДДУ (fedstat 38088 — Росреестр через EMISS) ──────────────
    # ⚠️  EMISS 38088 содержит данные только за 2010–2016!
    #    Данные 2017+ загружены из другого источника (Excel Росреестра)
    #    и хранятся в БД; повторная загрузка через fetch_fedstat охватывает
    #    только исторический период. DO NOTHING не затронет существующие точки.
    #
    # Регион: dim38488 (не dim57831!), РФ = 1576112
    # period_filter=monthly: «I квартал»..«IV квартал» есть в CUMULATIVE_QUARTERS
    {
        "fedstat_id": "38088",
        "code":       "5.1",
        "name":       "Общее количество ДДУ (Росреестр)",
        "unit":       "ед.",
        "periodicity": "quarterly",
        "period_type": "period",
        "category":   "demand",
        "source":     "rosreestr",
        "divisor":    1,
        "years":      list(range(2010, 2017)),   # данные в EMISS 38088 только до 2016
        "period_filter": "monthly",
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=33560"
            "&lineObjectIds=38488"
            "&columnObjectIds=3"
            "&selectedFilterIds=0_38088"
            "&selectedFilterIds=30611_950475"
            "&selectedFilterIds=33560_1540222"   # I квартал
            "&selectedFilterIds=33560_1540224"   # II квартал
            "&selectedFilterIds=33560_1540226"   # III квартал
            "&selectedFilterIds=33560_1540227"   # IV квартал
            "&selectedFilterIds=38488_1576112"   # Российская Федерация
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        "row_filter":  {"dim38488": "Российская Федерация"},
    },

    # ── 1.2 Среднедушевые денежные доходы (fedstat 57039) ────────────────────
    # Особый формат: кварталы закодированы в ключах значений, не в dim33560
    # dim{YEAR}_{Q_ID}_d{HASH}_i{IND} → значение
    # Q_ID: 1540222=Q1, 1540224=Q2, 1540226=Q3, 1540227=Q4
    {
        "fedstat_id": "57039",
        "code":       "1.2",
        "name":       "Среднедушевые денежные доходы населения",
        "unit":       "руб. / мес.",
        "periodicity": "quarterly",
        "period_type": "period",
        "category":   "macro",
        "source":     "rosstat",
        "divisor":    1,
        "years":      list(range(2012, 2027)),
        "period_filter": "quarters_in_row",
        "quarter_ids": {
            "1540222": (1,  "Q1"),
            "1540224": (4,  "Q2"),
            "1540226": (7,  "Q3"),
            "1540227": (10, "Q4"),
        },
        "payload_base": (
            "lineObjectIds=0&lineObjectIds=30611&lineObjectIds=57831"
            "&columnObjectIds=3&columnObjectIds=33560"
            "&selectedFilterIds=0_57039"
            "&selectedFilterIds=30611_950351"
            "&selectedFilterIds=33560_1540222"
            "&selectedFilterIds=33560_1540224"
            "&selectedFilterIds=33560_1540226"
            "&selectedFilterIds=33560_1540227"
            "&selectedFilterIds=57831_1688487"
            "&selectedFilterIds=57831_1688488"
            "&selectedFilterIds=57831_1688489"
            "&selectedFilterIds=57831_1688490"
            "&selectedFilterIds=57831_1688491"
            "&selectedFilterIds=57831_1688492"
            "&selectedFilterIds=57831_1688493"
            "&selectedFilterIds=57831_1688494"
            "&selectedFilterIds=57831_1688495"
            "&selectedFilterIds=57831_1688496"
            "&selectedFilterIds=57831_1688497"
            "&selectedFilterIds=57831_1688498"
            "&selectedFilterIds=57831_1688499"
            "&selectedFilterIds=57831_1688500"
            "&selectedFilterIds=57831_1688501"
            "&selectedFilterIds=57831_1688502"
            "&selectedFilterIds=57831_1688503"
            "&selectedFilterIds=57831_1688504"
            "&selectedFilterIds=57831_1688505"
            "&selectedFilterIds=57831_1688506"
            "&selectedFilterIds=57831_1688507"
            "&selectedFilterIds=57831_1688508"
            "&selectedFilterIds=57831_1688509"
            "&selectedFilterIds=57831_1688510"
            "&selectedFilterIds=57831_1688511"
            "&selectedFilterIds=57831_1688513"
            "&selectedFilterIds=57831_1688514"
            "&selectedFilterIds=57831_1688515"
            "&selectedFilterIds=57831_1688516"
            "&selectedFilterIds=57831_1688517"
            "&selectedFilterIds=57831_1688518"
            "&selectedFilterIds=57831_1688519"
            "&selectedFilterIds=57831_1688521"
            "&selectedFilterIds=57831_1688522"
            "&selectedFilterIds=57831_1688523"
            "&selectedFilterIds=57831_1688524"
            "&selectedFilterIds=57831_1688525"
            "&selectedFilterIds=57831_1688526"
            "&selectedFilterIds=57831_1688527"
            "&selectedFilterIds=57831_1688528"
            "&selectedFilterIds=57831_1688529"
            "&selectedFilterIds=57831_1688530"
            "&selectedFilterIds=57831_1688531"
            "&selectedFilterIds=57831_1688532"
            "&selectedFilterIds=57831_1688533"
            "&selectedFilterIds=57831_1688534"
            "&selectedFilterIds=57831_1688535"
            "&selectedFilterIds=57831_1688536"
            "&selectedFilterIds=57831_1688537"
            "&selectedFilterIds=57831_1688538"
            "&selectedFilterIds=57831_1688539"
            "&selectedFilterIds=57831_1688540"
            "&selectedFilterIds=57831_1688541"
            "&selectedFilterIds=57831_1688542"
            "&selectedFilterIds=57831_1688543"
            "&selectedFilterIds=57831_1688545"
            "&selectedFilterIds=57831_1688546"
            "&selectedFilterIds=57831_1688547"
            "&selectedFilterIds=57831_1688548"
            "&selectedFilterIds=57831_1688549"
            "&selectedFilterIds=57831_1688550"
            "&selectedFilterIds=57831_1688551"
            "&selectedFilterIds=57831_1688552"
            "&selectedFilterIds=57831_1688553"
            "&selectedFilterIds=57831_1688554"
            "&selectedFilterIds=57831_1688555"
            "&selectedFilterIds=57831_1688556"
            "&selectedFilterIds=57831_1688557"
            "&selectedFilterIds=57831_1688559"
            "&selectedFilterIds=57831_1688560"
            "&selectedFilterIds=57831_1688561"
            "&selectedFilterIds=57831_1688562"
            "&selectedFilterIds=57831_1688563"
            "&selectedFilterIds=57831_1688564"
            "&selectedFilterIds=57831_1688565"
            "&selectedFilterIds=57831_1688566"
            "&selectedFilterIds=57831_1688568"
            "&selectedFilterIds=57831_1688571"
            "&selectedFilterIds=57831_1688573"
            "&selectedFilterIds=57831_1688574"
            "&selectedFilterIds=57831_1688575"
            "&selectedFilterIds=57831_1688576"
            "&selectedFilterIds=57831_1688577"
            "&selectedFilterIds=57831_1688578"
            "&selectedFilterIds=57831_1688579"
            "&selectedFilterIds=57831_1688581"
            "&selectedFilterIds=57831_1688582"
            "&selectedFilterIds=57831_1688583"
            "&selectedFilterIds=57831_1688584"
            "&selectedFilterIds=57831_1688585"
            "&selectedFilterIds=57831_1688586"
            "&selectedFilterIds=57831_1688587"
            "&selectedFilterIds=57831_1692937"
            "&selectedFilterIds=57831_1692938"
            "&selectedFilterIds=57831_1692939"
            "&selectedFilterIds=57831_1692940"
            "&selectedFilterIds=57831_1695534"
            "&selectedFilterIds=57831_1795276"
            "&selectedFilterIds=57831_1795277"
            "&selectedFilterIds=57831_1849012"
        ),
        "year_param":  "selectedFilterIds=3_{year}",
        # Динамический фильтр по году задаётся в коде (см. quarters_in_row парсер)
        "row_filter":  None,
        "row_filter_by_year": {
            # 2012–2022: полная РФ
            "default": {"dim57831": "Российская Федерация"},
            # 2023+: без новых субъектов
            2023: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2024: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2025: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
            2026: {"dim57831": "Российская Федерация без учета новых субъектов (с 01.01.2023)"},
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Fedstat клиент
# ─────────────────────────────────────────────────────────────────────────────

class FedstatClient:
    BASE_URL = "https://www.fedstat.ru"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/142.0.0.0 YaBrowser/25.12.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ru,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.fedstat.ru",
        })

    def init_session(self, fedstat_id: str):
        """Открывает страницу индикатора для получения JSESSIONID и cookies."""
        url = f"{self.BASE_URL}/indicator/{fedstat_id}"
        self.session.headers["Referer"] = f"{self.BASE_URL}/"
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=60)
                r.raise_for_status()
                self.session.headers["Referer"] = url
                cookies = dict(self.session.cookies)
                log.info(f"  Сессия: {list(cookies.keys())}")
                return
            except Exception as e:
                if attempt < 2:
                    log.warning(f"  init_session попытка {attempt+1}/3: {e}")
                    time.sleep(5)
                else:
                    raise

    def fetch_year(self, fedstat_id: str, year: int,
                   payload_base: str, year_param: str) -> list:
        """POST-запрос за один год, возвращает results из JSON."""
        url = f"{self.BASE_URL}/indicator/dataGrid.do?id={fedstat_id}"
        year_str = year_param.format(year=year)
        payload  = payload_base + "&" + year_str

        for attempt in range(3):
            try:
                r = self.session.post(url, data=payload, timeout=60)
                r.raise_for_status()

                if not r.text.strip():
                    log.debug(f"  {year}: пустой ответ")
                    return []

                data = r.json()
                return data.get("results", [])

            except requests.exceptions.JSONDecodeError:
                log.debug(f"  {year}: не JSON — {r.text[:80]}")
                return []
            except Exception as e:
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                else:
                    log.warning(f"  {year}: ошибка {e}")
                    return []
        return []


def extract_value(row, year):
    """Извлекает числовое значение из строки результатов."""
    # Ключ выглядит как dim2017_d47431955_i2189
    pattern = re.compile(rf"^dim{year}_")
    for key, val in row.items():
        if pattern.match(key) and val not in (None, "", "...", "—"):
            raw = str(val).replace(",", ".").replace("\xa0", "").replace(" ", "")
            try:
                f = float(raw)
                if not math.isnan(f) and not math.isinf(f):
                    return f
            except ValueError:
                pass
    return None


def row_matches(row: dict, row_filter: dict) -> bool:
    """Проверяет что строка соответствует фильтру."""
    if not row_filter:
        return True
    return all(row.get(k) == v for k, v in row_filter.items())


def extract_quarters_from_row(row: dict, year: int, quarter_ids: dict) -> dict:
    """
    Извлекает квартальные значения из строки типа 57039 (доходы).
    
    В этом формате кварталы закодированы в именах ключей:
      dim{YEAR}_{QUARTER_ID}_d{HASH}_i{IND} → значение
    
    quarter_ids: {q_id: (month, label)} — маппинг ID квартала → квартал
    Возвращает: {(year, month): value}
    """
    import re
    result = {}
    for key, val in row.items():
        for q_id, (month, label) in quarter_ids.items():
            pattern = rf"^dim{year}_{q_id}_"
            if re.match(pattern, key) and val not in (None, "", "...", "—"):
                raw = str(val).replace(",", ".").replace(" ", "").replace(" ", "")
                try:
                    f = float(raw)
                    if not math.isnan(f) and not math.isinf(f):
                        result[(year, month, label)] = f
                except ValueError:
                    pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# БД
# ─────────────────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )

def get_last_date(conn, code: str):
    """Возвращает MAX(period_date) для индикатора с кодом code, или None."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT MAX(dp.period_date)
            FROM data_points dp
            JOIN indicators i ON i.id = dp.indicator_id
            WHERE i.code = %s
        """, (code,))
        row = cur.fetchone()
        return row[0] if row else None

def get_id(conn, table, col, val):
    with conn.cursor() as cur:
        cur.execute(f"SELECT id FROM {table} WHERE {col} = %s", (val,))
        row = cur.fetchone()
        return row[0] if row else None

def upsert_indicator(conn, ind, cat_id, src_id):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO indicators
                (code, name, unit, periodicity, period_type, geo_level,
                 category_id, source_id, is_public, chart_type, sort_order)
            VALUES (%s,%s,%s,%s,%s,'russia',%s,%s,TRUE,'line',0)
            ON CONFLICT (code) DO UPDATE SET
                name=EXCLUDED.name, unit=EXCLUDED.unit,
                periodicity=EXCLUDED.periodicity,
                period_type=EXCLUDED.period_type,
                last_updated=NOW()
            RETURNING id
        """, (ind["code"], ind["name"], ind["unit"],
              ind["periodicity"], ind["period_type"],
              cat_id, src_id))
        return cur.fetchone()[0]

def upsert_points(conn, ind_id, points):
    if not points: return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO data_points (indicator_id, period_date, period_label, value)
            VALUES %s
            ON CONFLICT (indicator_id, period_date) DO NOTHING
        """, [(ind_id, p["date"], p["label"], p["value"]) for p in points])
        return cur.rowcount   # кол-во фактически вставленных строк


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Фильтрация по кодам: python3 fetch_fedstat.py 1.2 1.3
    # Без аргументов — запускает все индикаторы
    target_codes = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    client = FedstatClient()
    conn   = get_conn()
    total  = 0

    indicators_to_run = [
        ind for ind in INDICATORS
        if target_codes is None or ind["code"] in target_codes
    ]
    if target_codes:
        log.info(f"Запуск только для кодов: {sorted(target_codes)}")
    log.info(f"Индикаторов к загрузке: {len(indicators_to_run)}\n")

    for ind in indicators_to_run:
        log.info(f"\n{'='*60}")
        log.info(f"[{ind['code']}] {ind['name']}")
        log.info(f"  fedstat/{ind['fedstat_id']}, делитель={ind['divisor']}, лет={len(ind['years'])}")

        cat_id = get_id(conn, "categories", "code", ind["category"])
        src_id = get_id(conn, "sources",    "code", ind["source"])
        if not cat_id or not src_id:
            log.error(f"  Категория '{ind['category']}' или источник '{ind['source']}' не найдены")
            continue

        try:
            # Инкрементальный фильтр: загружаем только с последнего года в БД
            last_date = get_last_date(conn, ind["code"])
            start_year = last_date.year if last_date else ind["years"][0]
            years_to_fetch = [y for y in ind["years"] if y >= start_year]
            log.info(f"  Последняя точка в БД: {last_date} → загружаем с {start_year} "
                     f"({len(years_to_fetch)} из {len(ind['years'])} лет)")

            # Инициализируем сессию (получаем cookies)
            client.init_session(ind["fedstat_id"])
            time.sleep(1)

            points = []
            period_filter = ind.get("period_filter")

            for year in years_to_fetch:
                results = client.fetch_year(
                    ind["fedstat_id"], year,
                    ind["payload_base"], ind["year_param"]
                )

                if period_filter == "monthly":
                    # Берём квартальные периоды (накопительные или порядковые) из dim33560
                    # Поддерживает row_filter_by_year (как quarters_in_row)
                    year_points = []
                    rf_by_year = ind.get("row_filter_by_year")
                    if rf_by_year:
                        row_f = rf_by_year.get(year, rf_by_year.get("default", {}))
                    else:
                        row_f = ind.get("row_filter") or {}
                    for row in results:
                        if not row_matches(row, row_f):
                            continue
                        period_str = row.get("dim33560", "").strip().lower()
                        if period_str not in CUMULATIVE_QUARTERS:
                            continue   # пропускаем одиночные месяцы и прочие периоды
                        month_start, q_label = CUMULATIVE_QUARTERS[period_str]
                        val = extract_value(row, year)
                        if val is None:
                            continue
                        divisor = ind.get("divisor", 1)
                        if divisor != 1:
                            val = val / divisor
                        year_points.append({
                            "date":  date(year, month_start, 1),
                            "label": f"{q_label} {year}",
                            "value": round(val, 4),
                        })
                    points.extend(year_points)
                    log.info(f"  {year}: {len(year_points)} кварталов (из {len(results)} строк)")

                elif period_filter == "true_monthly":
                    # Помесячные данные: каждая строка = один конкретный месяц (dim33560)
                    # Используется для ввода жилья (34118): 12 строк на год
                    year_points = []
                    rf_by_year = ind.get("row_filter_by_year")
                    if rf_by_year:
                        row_f = rf_by_year.get(year, rf_by_year.get("default", {}))
                    else:
                        row_f = ind.get("row_filter") or {}
                    for row in results:
                        if not row_matches(row, row_f):
                            continue
                        period_str = row.get("dim33560", "").strip().lower()
                        if period_str not in MONTH_NAMES:
                            continue   # пропускаем накопительные периоды и кварталы
                        month_num, m_label = MONTH_NAMES[period_str]
                        val = extract_value(row, year)
                        if val is None:
                            continue
                        divisor = ind.get("divisor", 1)
                        if divisor != 1:
                            val = val / divisor
                        year_points.append({
                            "date":  date(year, month_num, 1),
                            "label": f"{m_label} {year}",
                            "value": round(val, 4),
                        })
                    points.extend(year_points)
                    log.info(f"  {year}: {len(year_points)} месяцев (из {len(results)} строк)")
                elif period_filter == "quarters_in_row":
                    # Формат доходов: кварталы в ключах одной строки
                    quarter_ids = ind.get("quarter_ids", {})
                    # Динамический фильтр: разные ключи для разных лет
                    rf_by_year = ind.get("row_filter_by_year")
                    if rf_by_year:
                        row_f = rf_by_year.get(year, rf_by_year.get("default", {}))
                    else:
                        row_f = ind.get("row_filter") or {}
                    year_points = []
                    for row in results:
                        if not row_matches(row, row_f):
                            continue
                        quarters = extract_quarters_from_row(row, year, quarter_ids)
                        divisor = ind.get("divisor", 1)
                        for (y, month, label), val in quarters.items():
                            if divisor != 1:
                                val = val / divisor
                            year_points.append({
                                "date":  date(y, month, 1),
                                "label": f"{label} {y}",
                                "value": round(val, 4),
                            })
                        break  # берём первую строку по фильтру (РФ в целом)
                    points.extend(year_points)
                    log.info(f"  {year}: {len(year_points)} кварталов (фильтр: {row_f.get('dim57831','?')[:30]})")

                else:
                    # Годовые данные — берём первую строку по фильтру
                    for row in results:
                        if not row_matches(row, ind.get("row_filter", {})):
                            continue
                        val = extract_value(row, year)
                        if val is None:
                            continue
                        divisor = ind.get("divisor", 1)
                        if divisor != 1:
                            val = val / divisor
                        points.append({
                            "date":  date(year, 1, 1),
                            "label": str(year),
                            "value": round(val, 4),
                        })
                        break

                    log.info(f"  {year}: {'OK — ' + str(round(points[-1]['value'], 2)) + ' ' + ind['unit'] if points and points[-1]['date'].year == year else 'нет данных'}")

                time.sleep(0.7)

            log.info(f"  Всего точек: {len(points)}")
            if points:
                log.info(f"  Диапазон: {points[0]['date'].year}–{points[-1]['date'].year}")

            ind_id = upsert_indicator(conn, ind, cat_id, src_id)
            n = upsert_points(conn, ind_id, points)
            conn.commit()
            total += n
            log.info(f"  [OK] Загружено в БД: {n} точек")

        except Exception as e:
            conn.rollback()
            log.error(f"  [ERROR] {e}")
            import traceback; traceback.print_exc()

        time.sleep(2)

    # Расчёт 2.1 (Всего = МЖС + ИЖС), если в этом запуске были 2.3 или 2.2
    # ⚠️  2.3 = «Жилые здания» (орг.) из fedstat; 2.2 = ИЖС из fedstat
    #     2.1 (grand total) = 2.3 + 2.2 — «Жилые здания, жилые помещения
    #     в нежилых зданиях и жилые дома, построенные населением»
    processed_codes = {ind["code"] for ind in indicators_to_run}
    if processed_codes & {"2.3", "2.2"}:
        log.info(f"\n{'='*60}")
        log.info("Расчёт 2.1 = 2.3 + 2.2 (Всего = МЖС + ИЖС, SQL, DO NOTHING)...")
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO data_points (indicator_id, period_date, period_label, value)
                    SELECT i.id,
                           a.period_date,
                           a.period_label,
                           round((a.value + b.value)::numeric, 4)
                    FROM data_points a
                    JOIN data_points b
                      ON b.period_date   = a.period_date
                     AND b.indicator_id  = (SELECT id FROM indicators WHERE code = '2.2')
                    JOIN indicators i ON i.code = '2.1'
                    WHERE a.indicator_id = (SELECT id FROM indicators WHERE code = '2.3')
                    ON CONFLICT (indicator_id, period_date) DO NOTHING
                """)
                n21 = cur.rowcount
            conn.commit()
            log.info(f"  [OK] Добавлено новых точек 2.1: {n21}")
            total += n21
        except Exception as e:
            conn.rollback()
            log.error(f"  [ERROR] расчёт 2.1: {e}")

    # Обновляем materialized view
    try:
        log.info(f"\n{'='*60}")
        log.info("Обновление materialized view...")
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
        conn.commit()
        log.info("Готово.")
    except Exception as e:
        log.error(f"Ошибка: {e}")

    conn.close()
    log.info(f"\nИтого загружено: {total} точек")


if __name__ == "__main__":
    main()
