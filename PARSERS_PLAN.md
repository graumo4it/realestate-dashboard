# План: восстановление системы обновления данных

## Контекст

Все три парсера в `parsers/` **никогда не запускались** и сломаны:
- `cbr.py` — скачивает не тот файл (находит `01_01_Participants.xlsx` вместо нужных файлов); ожидает структуру «месяцы-строки / годы-столбцы», а реальная CBR-таблица транспонирована (даты = столбцы `01.MM.YYYY`, метрики = строки)
- `domrf.py` — API `наш.дом.рф/opendata` закрыт WAF (403 Forbidden); данные уже хранятся локально в `migration/domrf_data/` в виде Excel-файлов платной базы
- `rosstat.py` — использует неверные EMISS IDs и сломанный JSON API (`fedstat.ru/api/data/{id}.json` возвращает HTML с ошибкой)

**Хорошая новость**: в `migration/fetch_fedstat.py` уже есть рабочий `FedstatClient` с корректными POST-запросами к fedstat.ru для 6 индикаторов (1.2, 1.3, 2.9, 2.11, 2.12, 2.13.ext). В `migration/` лежат готовые скрипты для обработки DomRF-файлов и субсидий CBR.

**Цель**: создать рабочую систему, которая:
1. Скачивает/читает актуальные данные из правильных источников
2. **Добавляет только новые периоды** — не перезаписывает существующие данные
3. Запускается по расписанию или по команде

---

## Принцип инкрементального обновления

**Правило**: для каждого индикатора парсер проверяет `MAX(period_date)` в БД — и добавляет только записи с датой **строго позже** этого максимума. Существующие данные не перезаписываются.

### Изменения в `parsers/base.py`

**1. Новый метод `get_last_dates()`**:
```python
def get_last_dates(self, codes: list[str]) -> dict[str, date]:
    """Возвращает {indicator_code: max_period_date} для переданных кодов."""
    with self.conn.cursor() as cur:
        cur.execute("""
            SELECT i.code, MAX(dp.period_date)
            FROM data_points dp
            JOIN indicators i ON i.id = dp.indicator_id
            WHERE i.code = ANY(%s)
            GROUP BY i.code
        """, (codes,))
        return {row[0]: row[1] for row in cur.fetchall()}
```

**2. Изменение `run()`** — фильтровать после парсинга, до upsert:
```python
codes = list({r["indicator_code"] for r in records})
last_dates = self.get_last_dates(codes)
new_records = [r for r in records
               if r["period_date"] > last_dates.get(r["indicator_code"], date.min)]
log.info(f"[{self.source_code}] Распарсено: {len(records)}, новых: {len(new_records)}")
rows = self.upsert_to_db(new_records)
```

**3. SQL** — изменить на `DO NOTHING` (защита от перезаписи):
```sql
ON CONFLICT (indicator_id, period_date) DO NOTHING
```

### Оптимизация для EMISS (`migration/fetch_fedstat.py`)

Перед циклом по годам — ограничивать диапазон последним годом в БД:
```python
last_date = get_last_date(conn, ind["code"])   # новая вспомогательная функция
start_year = last_date.year if last_date else ind["years"][0]
years_to_fetch = [y for y in ind["years"] if y >= start_year]
```

При пустой БД (первый запуск) — `date.min` → все записи проходят фильтр → загружается полная история.

---

## Track A — Переписать `parsers/cbr.py`

### Источники

| Файл | URL (от cbr.ru) | Индикаторы |
|------|-----------------|------------|
| `02_02_Mortgage.xlsx` | `/vfs/statistics/BankSector/Mortgage/02_02_Mortgage.xlsx` | 6.1–6.6 (всего), 6.19–6.21 (долг всего) |
| `02_03_Scpa_mortgage.xlsx` | `/vfs/statistics/BankSector/Mortgage/02_03_Scpa_mortgage.xlsx` | 6.7–6.12 (первичный/ДДУ), 6.22–6.24 (долг первич.) |
| `02_41_Mortgage_ihc.xlsx` | `/vfs/statistics/banksector/mortgage/02_41_Mortgage_ihc.xlsx` | 6.70–6.87 (ИЖС) |
| `Статистические_ряды.xlsx` | ссылка с текстом «Статистические ряды» на странице cbr.ru/statistics/bank_sector/mortgage/ | 6.36–6.65 (субсидии) |

**Вторичный рынок рассчитывается** в парсере: `6.13 = 6.1 − 6.7`, ..., `6.18 = 6.6 − 6.12`. Долг вторичного: `6.25 = 6.19 − 6.22`, ...

### Формат данных CBR (общий для 02_02 и 02_03)
- **Структура**: строка 0 = даты (`01.MM.YYYY`), следующие строки = метрики
- **Лист**: `"в рублях"` (для `02_02_Mortgage.xlsx`) / аналогичный для `02_03_Scpa_mortgage.xlsx`
- **Дата→период**: колонка `01.02.2026` = данные **за январь 2026** (конвенция ЦБ: дата отчёта = следующий месяц):
  `period_date = date(YYYY, MM-1, 1)` (с обработкой января: `date(YYYY-1, 12, 1)`)

### Маппинг метрик (строки → коды)

`02_02_Mortgage.xlsx` "в рублях" → 6.1-6.6 и 6.19-6.21:
```
"Количество предоставленных кредитов за месяц"   → 6.1
"Объем предоставленных кредитов за месяц"         → 6.2
"Средневзвешенная ставка"                         → 6.3
"Средневзвешенный срок"                           → 6.4
"Средний размер кредита"                          → 6.5
"Средний размер платежа" / "платёж"               → 6.6
"Задолженность по предоставленным кредитам"       → 6.19  (итоговая строка, не подстрока)
"Просроченная задолженность"                      → 6.20
"Доля просроченной"                               → 6.21
```
`02_03_Scpa_mortgage.xlsx` → аналогично → 6.7-6.12 и 6.22-6.24.

> ⚠️ **При реализации**: сначала вывести `df.iloc[:, 0].dropna().tolist()` для каждого файла — уточнить точные строковые подстроки для row_filter.

### Субсидии
Переиспользовать логику из `migration/migrate_subsidy_update.py`:
- Лист `"01_02_01"`, маппинг строк из `ROW_TO_CODE`
- Загружать **только** периоды, где строка «нет данных» на листе `"01_02_03"` == 0

### Структура класса
```python
class CBRParser(BaseParser):
    BASE_URL = "https://cbr.ru"
    FILES = {
        "total":   "/vfs/statistics/BankSector/Mortgage/02_02_Mortgage.xlsx",
        "primary": "/vfs/statistics/BankSector/Mortgage/02_03_Scpa_mortgage.xlsx",
        "igs":     "/vfs/statistics/banksector/mortgage/02_41_Mortgage_ihc.xlsx",
    }

    def fetch_raw(self) -> dict:
        # Скачивает all 3 статичных файла + ищет ссылку на Статистические_ряды.xlsx
        # Возвращает {"total": bytes, "primary": bytes, "igs": bytes, "subsidy": bytes}

    def parse(self, raw: dict) -> list[dict]:
        # parse_mortgage_file(raw["total"], TOTAL_ROW_MAP) → 6.1-6.6, 6.19-6.21
        # parse_mortgage_file(raw["primary"], PRIMARY_ROW_MAP) → 6.7-6.12, 6.22-6.24
        # calc_secondary(total, primary) → 6.13-6.18, 6.25-6.27 (арифметика)
        # parse_igs(raw["igs"]) → 6.70-6.87
        # parse_subsidy(raw["subsidy"]) → 6.36-6.65
        # Возвращает объединённый список records
```

---

## Track B — Расширить `migration/fetch_fedstat.py` + упростить `parsers/rosstat.py`

### Новые INDICATOR-записи для `fetch_fedstat.py`

| Код | fedstat ID | Тип периода | Примечания |
|-----|-----------|-------------|-----------|
| `2.1` | 34118 | monthly | Ввод жилья «всего» (Жилые здания + нежилые); `row_filter` по строке «Жилые здания...» |
| `2.2` | 34118 | monthly | Ввод жилья ИЖС («Жилые дома, построенные населением»); тот же payload, другой `row_filter` |
| `2.3` | —  | monthly | **Расчётный**: `2.3 = 2.1 − 2.2` — добавить SQL-расчёт после upsert 2.1 и 2.2 |
| `4.4` | 31452 | quarterly | Цены первичного рынка; `row_filter` по типу жилья «первичный» |
| `4.5` | 31452 | quarterly | Цены вторичного рынка; тот же payload, другой `row_filter` |
| `2.13` | 43507 | annual | Благоустройство жилфонда; десятичный разделитель `.` — обработать в `extract_value()` |
| `5.1` | 38088 | quarterly | Кол-во ДДУ (Росреестр через EMISS) |

**payload_base** для каждого нового индикатора нужно захватить из браузера:
1. Открыть `fedstat.ru/indicator/{ID}`
2. DevTools → Network → Filter XHR
3. Нажать кнопку «Показать» на странице
4. Найти POST на `/indicator/dataGrid.do`
5. Скопировать Form Data → вставить в `payload_base`

**Фильтр по регионам** (как в 1.2): для 2.1/2.2/4.4/4.5 использовать `row_filter_by_year` с ключами 2023+: `"Российская Федерация без учета новых субъектов (с 01.01.2023)"`.

**Расчёт 2.3** после upsert 2.1 и 2.2:
```sql
INSERT INTO data_points (indicator_id, period_date, period_label, value)
SELECT i.id, a.period_date, a.period_label, a.value - b.value
FROM data_points a
JOIN data_points b ON b.period_date = a.period_date
  AND b.indicator_id = (SELECT id FROM indicators WHERE code = '2.2')
JOIN indicators i ON i.code = '2.3'
WHERE a.indicator_id = (SELECT id FROM indicators WHERE code = '2.1')
ON CONFLICT (indicator_id, period_date) DO NOTHING
```

### `parsers/rosstat.py` — делегирующая обёртка

```python
class RosstatParser(BaseParser):
    source_code = "rosstat"

    def fetch_raw(self):   return None
    def parse(self, raw):  return []

    def run(self):
        """Запускает migration/fetch_fedstat.py как subprocess."""
        import subprocess, sys, re
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "migration/fetch_fedstat.py")],
            capture_output=True, text=True
        )
        m = re.search(r"Итого загружено: (\d+)", result.stdout or "")
        rows = int(m.group(1)) if m else 0
        return {
            "status": "success" if result.returncode == 0 else "error",
            "rows": rows,
            "error": result.stderr or None
        }
```

---

## Track C — Переписать `parsers/domrf.py` как оркестратор

API DomRF заблокирован. Данные в `migration/domrf_data/` (три папки: `apartments/`, `matrix_projects/`, `sales_matrix/`). Логику обработки реализуют существующие скрипты.

```python
class DomRFParser(BaseParser):
    source_code = "domrf"
    SCRIPTS = [
        "migration/migrate_apartments.py",
        "migration/migrate_matrix_projects.py",
        "migration/migrate_sales_matrix.py",
        "migration/migrate_under_construction_domrf.py",
        "migration/calc_sales_pace.py",
        "migration/calc_sales_pace_mm.py",
        "migration/calc_developer_activity.py",
        "migration/calc_demand_activity.py",
        "migration/calc_avg_apt_area.py",
    ]

    def fetch_raw(self):  return None
    def parse(self, raw): return []

    def run(self):
        # Запускает скрипты последовательно через subprocess
        # Не вызывает upsert_to_db / _refresh_view (скрипты делают это сами)
        # Проверяет наличие новых файлов в domrf_data/ по mtime папки
        # Возвращает {"status": ..., "rows": total, "error": ...}
```

> Каждый migrate-скрипт должен выводить в stdout строку вида `Upserted: N rows` — парсер суммирует N.

---

## Track D — Обновить `parsers/scheduler.py`

```python
# Расписание: ежемесячное (данные CBR и EMISS выходят раз в месяц)
scheduler.add_job(lambda: CBRParser().run(),    'cron', day=10, hour=8)
scheduler.add_job(lambda: RosstatParser().run(),'cron', day=10, hour=9)
# DomRF: запускать после ручного добавления файлов (15–20 числа)
scheduler.add_job(lambda: DomRFParser().run(),  'cron', day='20', hour=10)
```

---

## Зависимости

Добавить в `parsers/requirements.txt`:
- `pyxlsb` — для `.xlsb` файлов DomRF (Квартирография, Матрица проектов)

Уже установлены: `requests`, `beautifulsoup4`, `APScheduler`, `python-dotenv`, `openpyxl`, `pandas`.

---

## Порядок реализации и промпты

### Шаг 1: base.py — инкрементальное обновление
### Шаг 2: CBR-парсер
### Шаг 3: Rosstat/EMISS — расширение fetch_fedstat.py
### Шаг 4: DomRF-оркестратор
### Шаг 5: Scheduler

*(Промпты для каждого шага — в отдельном разделе ниже)*

---

## Файлы к изменению

| Файл | Действие |
|------|----------|
| `parsers/base.py` | Добавить `get_last_dates()`, изменить `run()` и `upsert_to_db()` |
| `parsers/cbr.py` | Полная переработка |
| `parsers/rosstat.py` | Полная переработка (делегирующая обёртка) |
| `parsers/domrf.py` | Полная переработка (оркестратор) |
| `parsers/scheduler.py` | Обновить расписание |
| `migration/fetch_fedstat.py` | Добавить инкрементальный фильтр + 7 новых INDICATOR-записей |
| `parsers/requirements.txt` | Добавить `pyxlsb` |

---

## Верификация

```bash
source venv/bin/activate

# 1. CBR dry-run (fetch + parse без записи в БД)
cd /путь/к/проекту
python3 -c "
import sys; sys.path.insert(0,'parsers')
from cbr import CBRParser
p = CBRParser()
raw = p.fetch_raw()
recs = p.parse(raw)
from collections import Counter
by_code = Counter(r['indicator_code'] for r in recs)
print(f'Итого: {len(recs)} записей, коды: {sorted(by_code.keys())}')
print('Диапазон дат:', min(r[\"period_date\"] for r in recs), '—', max(r[\"period_date\"] for r in recs))
"
# Ожидать: ~1000+ записей, коды 6.1–6.87, последняя дата ≥ 2026-02-01

# 2. EMISS — проверить два индикатора
python3 migration/fetch_fedstat.py 1.2 1.3
# Ожидать: финальная строка "Итого загружено: N точек"

# 3. Проверка инкрементальности (запустить CBR дважды)
python3 parsers/cbr.py  # первый запуск → N строк
python3 parsers/cbr.py  # второй запуск → 0 строк ("новых: 0")

# 4. Проверка свежих данных в БД
psql -U postgres -d realestate -c "
SELECT i.code, MAX(dp.period_date) as latest, COUNT(*) as n
FROM data_points dp JOIN indicators i ON i.id = dp.indicator_id
WHERE i.code IN ('6.1','6.2','6.3','6.7','1.2','1.3','2.1','3.1','4.1')
GROUP BY i.code ORDER BY i.code;
"
```
