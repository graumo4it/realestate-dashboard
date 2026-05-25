# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Быстрый старт

```bash
# Активировать venv (всегда перед Python-скриптами)
source venv/bin/activate

# Backend (порт 8001)
cd backend && uvicorn app.main:app --reload --port 8001

# Frontend (порт 3000)
cd frontend && nohup python3 -m http.server 3000 > /tmp/frontend.log 2>&1 &
lsof -ti:3000 | xargs kill -9  # остановить

# Запустить планировщик (caffeinate не даёт Маку засыпать во время выполнения)
source venv/bin/activate
cd parsers && caffeinate -s nohup python scheduler.py > /tmp/scheduler.log 2>&1 &
tail -f /tmp/scheduler.log   # следить за логами
kill $(pgrep -f scheduler.py) # остановить

# Запустить парсер вручную
source venv/bin/activate
cd parsers && python cbr.py      # или domrf.py, rosstat.py

# Запустить расчётный скрипт
source venv/bin/activate
cd migration && python calc_sales_pace.py

# После любого upsert данных:
psql -U postgres -d realestate -c "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"

# Применить новую миграцию:
psql -U postgres -d realestate -f migration/001_init.sql
```

БД: PostgreSQL 16, `realestate`, localhost:5432. Настройки через `.env` (читается `pydantic-settings`): `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `CORS_ORIGINS`.

## Архитектура

```
Источники (ЦБ РФ, ЕМИСС, ДОМ.РФ, Росстат)
  → Python-парсеры (GitHub Actions cron)
  → PostgreSQL 16  (sources / categories / indicators / data_points)
  → FastAPI backend (порт 8001 локально, 8000 в Docker)
  → Vanilla HTML + ECharts 5.4.3 (без Node.js, без сборщика)
```

### Стек

- **Backend:** FastAPI + SQLAlchemy 2 (sync) + psycopg2 + Pydantic v2
- **Frontend:** HTML5 + CSS-переменные + Vanilla JS + ECharts 5.4.3 (CDN cdnjs)
- **Шрифты:** Playfair Display (заголовки), IBM Plex Sans (тело), IBM Plex Mono (числа)
- **Продакшн:** Docker Compose (db + backend + nginx), автодеплой через GitHub Actions

## Схема БД

Четыре основных таблицы + materialized view:

| Таблица | Назначение |
|---------|-----------|
| `sources` | Источники данных (ЦБ РФ, ДОМ.РФ и т.д.) |
| `categories` | Тематические разделы (mortgage_base, prices, demand …) |
| `indicators` | Метаданные временного ряда: `code`, `unit`, `periodicity`, `period_type`, `chart_type` |
| `data_points` | Только абсолютные значения: `(indicator_id, period_date)` — UNIQUE |
| `update_jobs` | Лог запусков парсеров: статус, кол-во upserted строк, ошибки |

**Materialized view `data_points_with_dynamics`** — все производные метрики (YoY, MoM через `LAG()`). Его надо обновлять после каждого upsert. Парсеры делают это автоматически (`BaseParser._refresh_view()`); ручной скрипт должен обновлять сам.

### Ключевые правила данных

- `data_points` хранит только абсолютные значения; YoY/MoM — только в `data_points_with_dynamics`
- Отсутствие данных = `NULL`, не `0` (ECharts рисует разрыв при `connectNulls: false`)
- `period_type`: `period` — значение за промежуток (ввод жилья, ипотека); `point_in_time` — значение на дату (задолженность, жилфонд)
- YoY для `unit='%'` — абсолютная разность в п.п., не относительная
- `period_date` = первый день периода: 2024-01-01 = январь 2024 / год 2024
- `is_public=false` скрывает индикатор из списков разделов, но он доступен через `/api/multi/data` и прямые запросы

## Backend

### Роутеры (`backend/app/routers/`)

| Файл | Ключевые маршруты |
|------|-------------------|
| `categories.py` | `GET /api/categories` |
| `indicators.py` | `GET /api/categories/{code}/indicators`, `/api/indicators/{code}`, `/api/indicators/{code}/data`, `/api/indicators/{code}/data.xlsx`, `/api/multi/data`, `/api/multi/data.xlsx`, `/api/search` |
| `meta.py` | `GET /api/meta/last-update` |

### Сервисы (`backend/app/services/`)

- **`data_service.py`** — все SQL-запросы к `data_points_with_dynamics`. `get_indicator_list_for_category` возвращает `List[IndicatorSummary]` (внутренний датакласс); роутер конвертирует в `IndicatorBrief` через `_summary_to_brief()`. Формула YoY/MoM вынесена в `_change_expr(value_col, prev_col, unit_col)` и используется в обоих запросах. Все строки доступаются по именам через `.mappings()`. `get_time_series` — полный ряд с динамикой.
- **`export_service.py`** — генерация `.xlsx` через `openpyxl`. Используется для одиночного и мульти-экспорта.

`window.API_BASE = 'http://localhost:8001/api'` — задаётся в каждом HTML-файле явно.

## Frontend

### Три «системных» страницы

- **`index.html`** — сетка категорий + поиск (через `/api/categories` и `/api/search`)
- **`category.html`** — список показателей раздела. Содержит JS-константу `COMBO_OVERRIDES` — правила замены/добавления карточек на ссылки комбо-страниц (логика только во frontend, БД не меняется). Константа `SUBSECTIONS` задаёт подразделы (section-headers) внутри страниц отдельных категорий; коды в ней — это «эффективные» коды карточек после применения `COMBO_OVERRIDES`. Категории с подразделами: `demand` (5 групп) и `prices` (2 группы).
- **`chart.html`** — график одного показателя (`?code=6.1`). Поддерживает переключатели периода (1г/3г/5л/Всё), режима (Значения/г-г/м-м), переключатель Квартал/Год для квартальных индикаторов, таблицу, KPI-блок, блок «Связанные показатели». Для квартальных показателей в режиме «Год» загружает official companion-индикатор `<code>.y` (если существует) вместо агрегации кварталов.

### 37 комбо-страниц

Используют `/api/multi/data?codes=...`. Каждая содержит:
- Константы `CODES` (mapping имён в коды) и `LABELS` (подписи серий)
- Опционально `KEYS` (массив ключей для фильтров серий) — **обязательно объявлять после `LABELS`**
- Инициализацию `PeriodToggle.injectButtons(toolbar, ...)` (шим AnnualToggle **удалён**)
- Горизонтальную панель фильтров серий

**Эталон разметки** горизонтальной панели фильтров: `subsidy-count.html`.

### JS-модули (`frontend/js/`)

| Файл | Назначение |
|------|-----------|
| `api.js` | `api.{categories,categoryIndicators,indicator,indicatorData,multiIndicatorData,...}` |
| `utils.js` | `fmtNum`, `fmtValue`, `fmtPct`, `fmtDate`, `fmtDateInline`, `deltaHtml`, `rangeStart`, `cleanName` |
| `sparkline.js` | Мини-графики для карточек на `category.html` |
| `chart-page.js` | Вся логика `chart.html`. Для квартальных показателей автоматически пытается загрузить companion-индикатор `<code>.y` (официальный годовой ряд из Росстата). |
| `period-toggle.js` | **v4.0.** `PeriodToggle.aggregate`, `aggregateWavg`, `injectButtons` (алиас `injectSelector`), `detectPeriodicity`. Шим `window.AnnualToggle` **удалён** — все страницы мигрированы на `PeriodToggle`. |
| `annual-toggle.js` | Устаревший модуль; заменён `period-toggle.js` (файл сохранён для истории) |

#### period-toggle.js: типы агрегации

| Тип | Применение |
|-----|-----------|
| `'sum'` | Ввод жилья, выдачи ипотек, счётные показатели |
| `'avg'` | Размер кредита, платёж, IHH, цены |
| `'wavg'` | Ставки и сроки — средневзвешенные по объёму выдач |

Страницы с `wavg` задают `window.AGG_TYPE = 'wavg'` и `window._WEIGHT_CODES = { код_ставки: код_объёма }` до загрузки `period-toggle.js`.

#### Расчёт динамики в period-toggle.js v4.0

- **Годовой ряд**: YoY = к предыдущей точке (одновременно предыдущий год).
- **Квартальный ряд**: YoY = к той же точке 4 квартала назад; QoQ = к предыдущему кварталу (сохраняется в `qoq_change_pct` и продублировано в `mom_change_pct` для обратной совместимости).
- Неполные кварталы (< 3 месяцев с данными) и годы (< 12) исключаются.

## Парсеры (`parsers/`)

⚠️ Три парсера (`cbr.py`, `domrf.py`, `rosstat.py`) требуют переработки — никогда не запускались, данные загружены вручную через Excel-миграции. Детали и план: `PARSERS_PLAN.md`. `domrf_web.py` — готов и протестирован.

Все парсеры наследуются от `BaseParser` (`parsers/base.py`). Шаблонный метод `run()`: подключение → `fetch_raw()` → `parse()` → фильтр новых периодов → `upsert_to_db()` → `REFRESH MATERIALIZED VIEW`.

**Принцип инкрементального обновления** (после переработки): `upsert_to_db` использует `ON CONFLICT DO NOTHING`; перед upsert отфильтровываются записи с `period_date ≤ MAX(period_date)` в БД для каждого индикатора — существующие данные не перезаписываются.

| Парсер | Показатели | Статус | Реальный источник |
|--------|-----------|--------|-------------------|
| `cbr.py` | 6.1–6.87 (ипотека) | ⚠️ Нужна переработка | `02_02_Mortgage.xlsx`, `02_03_Scpa_mortgage.xlsx`, `02_41_Mortgage_ihc.xlsx`, `Статистические_ряды.xlsx` с cbr.ru |
| `domrf.py` | 3.x, 4.1, 4.8–4.9, 5.x (DomRF) | ⚠️ Нужна переработка → оркестратор | Локальные Excel в `migration/domrf_data/`, обработка через `migrate_*.py` |
| `domrf_web.py` | 3.1–3.4, 3.17–3.19 (ЕИСЖС) | ✅ Готов | Скачивает `01_01_stockvariablesexsales.xlsx` с наш.дом.рф напрямую |
| `rosstat.py` | 1.x, 2.x, 4.4–4.5, 5.1 | ⚠️ Нужна переработка → обёртка | `migration/fetch_fedstat.py` (POST-запросы к fedstat.ru) |

**Рабочие компоненты** (не требуют изменений):
- `migration/fetch_fedstat.py` — FedstatClient с корректными EMISS IDs и payload для: 1.2 (57039), 1.3 (57823), 2.9 (40454), 2.11 (40457), 2.12 (40456), 2.13.ext (40458). Запускать: `python migration/fetch_fedstat.py [код ...]`
- `migration/migrate_apartments.py`, `migrate_matrix_projects.py`, `migrate_sales_matrix.py` — обработка файлов DomRF
- `migration/migrate_subsidy_update.py` — субсидии CBR из `Статистические_ряды.xlsx`

⚠️ fedstat.ru — **только локально** (облачные IP блокируются, скорость ≤ 1 req/sec). GitHub Actions для парсеров не создаются.

**Расписание** (`parsers/scheduler.py`, APScheduler):
- 5-е, 08:00 UTC — `subsidy_first` (субсидии ДОМ.РФ, первый прогон)
- 10-е, 08:00 UTC — `day10`: CBR → Росреестр (5.1) → Rosstat/EMISS (1.3, 2.x, 4.x) → fetch_income_rosstat (1.2) → calc_annual_companion (1.3.y) → calc_housing_per_capita (2.6/2.7/2.8) → население 1.1 → calc_housing_provision (2.10) → calc_housing_need (5.12–5.15)
- 20-е, 10:00 UTC — `day20`: DomRF → DomRF Web → calc_avg_apt_area (3.5) → calc_affordability (5.10/5.11)

DomRF требует ручной загрузки файлов в `migration/domrf_data/`.

⚠️ `domrf_web.py` доступен только с российских IP (ЕИСЖС геоблокирует зарубежные запросы).

**CBR-конвенция дат**: колонка `01.02.2026` в Excel = данные **за январь 2026** (дата отчёта = первое число следующего месяца). При парсинге: `period_date = date(YYYY, MM-1, 1)`.

## Annual companion-индикаторы (суффикс `.y`)

Companion-индикаторы хранят **годовое** значение для квартальных рядов — отображаются на `chart.html` в режиме «Год». `periodicity='annual'`, `is_public=false`. Миграция: `migration/003_annual_companion_indicators.sql`.

| Код | Название | Способ обновления |
|-----|---------|-------------------|
| `1.2.y` | Среднедушевые доходы населения (годовые) | Ручной: `load_rosstat_annual.py` (строка «Год» из `urov_10kv_Nkv-YYYY.xlsx`) |
| `1.3.y` | Среднемесячная зарплата (годовая) | **Авто**: `calc_annual_companion.py` в scheduler (10-е, после rosstat.py) |

**1.3.y = среднее четырёх кварталов 1.3** (`(Q1+Q2+Q3+Q4)/4`). Рассчитывается автоматически для каждого года, где все 4 квартала присутствуют.

**1.2.y** — строка «Год» из файла `urov_10kv_Nkv-YYYY.xlsx` (rosstat.gov.ru/folder/13397). Обновляется вручную раз в год:
```bash
source venv/bin/activate
cd migration
python load_rosstat_annual.py --file1 /tmp/urov_10kv_Nkv-YYYY.xlsx
```

**1.2** (квартальные данные) — парсится автоматически скриптом `fetch_income_rosstat.py` (10-е, в scheduler): скачивает `urov_10kv_Nkv-YYYY.xlsx` напрямую с Росстата, читает квартальные строки.

## Расчётные индикаторы (`migration/calc_*.py`)

Пишут результат напрямую в `data_points` и обновляют view.

**В составе scheduler (автоматически):**

| Код | Скрипт | Триггер |
|-----|--------|---------|
| `1.3.y` Зарплата годовая | `calc_annual_companion.py` | После rosstat.py (10-е) |
| `2.6`, `2.7`, `2.8` Ввод жилья на душу | `calc_housing_per_capita.py` | После rosstat.py (10-е) |
| `2.10` Обеспеченность жильём | `calc_housing_provision.py` | После migrate_population (10-е) |
| `3.5` Средняя площадь квартир | `calc_avg_apt_area.py` | После domrf_web.py (20-е) |
| `3.7` Девелоперская активность | `calc_developer_activity.py` | В составе domrf.py (20-е) |
| `5.3` Активность спроса | `calc_demand_activity.py` | В составе domrf.py (20-е) |
| `5.9`, `5.9.ma12` Темп продаж квартир | `calc_sales_pace.py` | В составе domrf.py (20-е) |
| `5.10` Доступность (зарплата/цена) | `calc_affordability.py` | После domrf_web.py (20-е) |
| `5.11` Доступность (ФЦП) | `calc_affordability_fcp.py` | После domrf_web.py (20-е) |
| `5.12–5.15 (.33/.38)` Потребность в жилье | `calc_housing_need.py` | После calc_housing_provision (10-е) |
| `5.22`, `5.22.ma12` Темп продаж машиномест | `calc_sales_pace_mm.py` | В составе domrf.py (20-е) |

**Только ручной запуск (раз в год):**

| Код | Скрипт |
|-----|--------|
| `1.2.y` Доходы годовые | `load_rosstat_annual.py` |

Население (1.1): захардкожено в скриптах, fedstat/31557 недоступен.

## Частые баги

| Симптом | Причина и решение |
|---------|-------------------|
| `TypeError: null … btn-filter-series` | Нет HTML-разметки панели фильтров — добавить по эталону `subsidy-count.html` |
| `ReferenceError: KEYS` | Константа `KEYS` не объявлена — объявить после `LABELS` |
| Страница сжалась в узкий столбик | После удаления `<aside>` добавить `display: block` override на `.chart-layout` |
| Дропдаун пустой | `buildDropdown()` не вызван в `init()` или упал раньше |
| Пустой график после переключения периодичности | `allData` подменён ссылкой вместо мутации — шим `period-toggle.js` мутирует `entry.series` |

## Продакшн

Docker Compose (`docker-compose.prod.yml`): три контейнера — `db` (postgres:16-alpine), `backend` (порт 8000), `nginx` (80/443). Конфигурация через `.env.prod`. Frontend отдаётся nginx как статика из `./frontend`. TLS через certbot (`certbot/conf`, `certbot/www`).

## Текущий статус (май 2026)

**В работе:**
1. Деплой на VPS
2. Применить `migration/004_cleanup.sql` секции 7–8 (sort_order для `demand` и `prices`) — ожидает визуальной проверки страниц категорий
3. **Переработка системы парсинга** (план: `PARSERS_PLAN.md`):
   - Шаг 1: `parsers/base.py` — инкрементальное обновление (`get_last_dates()`, `DO NOTHING`)
   - Шаг 2: `parsers/cbr.py` — переписать под правильные файлы CBR
   - Шаг 3: `migration/fetch_fedstat.py` — добавить 7 новых EMISS-индикаторов (2.1, 2.2, 2.3, 4.4, 4.5, 2.13, 5.1)
   - Шаг 4: `parsers/rosstat.py` (обёртка над fetch_fedstat.py) + `parsers/domrf.py` (оркестратор migrate_*.py)

**Недавно завершено:**
- ✅ **Аудит обновления индикаторов** (`migration/generate_update_map.py`, `indicator_update_map.xlsx`): полная карта 157 индикаторов с цветовой разметкой; исправлены найденные проблемы:
  - Удалены 6.46–6.67.1 (ЦБ РФ ДДУ — 25 индикаторов без источника обновления) + `mm_count`/`mm_area` → `migration/006_delete_cbr_ddu_indicators.sql`
  - `migrate_sales_matrix.py` — изменены коды `mm_count`→`5.20`, `mm_area`→`5.21` (исправлен разрыв в цепочке 5.20→5.22)
  - Создан `calc_housing_per_capita.py` (2.6/2.7/2.8 = ввод/население); добавлен в scheduler после rosstat.py
- ✅ **`parsers/domrf_web.py`** — новый готовый парсер: скачивает `01_01_stockvariablesexsales.xlsx` с наш.дом.рф, обновляет 3.1, 3.2, 3.3, 3.4, 3.17, 3.18, 3.19 (77 месяцев, 2020–2026); идемпотентен (повторный запуск → 0 новых строк); зарегистрирован в `scheduler.py` (day=20, hour=10, minute=30)
- ✅ **Аудит системы парсинга**: все три парсера никогда не запускались; выявлены причины; составлен план переработки (`PARSERS_PLAN.md`); установлены зависимости (`requests`, `bs4`, `APScheduler` в venv)
- ✅ **UX-правки `category.html`**: счётчик в подзаголовке теперь показывает `indicators.length` (кол-во видимых карточек после `COMBO_OVERRIDES`) вместо `rawIndicators.length` (всё из API); убрана надпись «Данные обновляются автоматически»
- ✅ **Аудит и очистка БД** (`migration/004_cleanup.sql`, `migration/004_db_audit_report.md`): убраны легаси-префиксы «X.X» из 92 названий индикаторов; исправлены единицы 5.10 (`кв.м/зарплату`); добавлены CHECK-ограничения (`chk_periodicity`, `chk_period_type`, `chk_chart_type`); устранены конфликты sort_order в `categories`; устранены дубли названий (3.7/uc_dev_activity, uc_new_active/total, 5.14.xx, apartments 1k-4k, 18 ипотека ИЖС 6.70–6.87); удалены устаревшие 3.13/3.15. Итог: 180 индикаторов, 10 394 точки, 18 категорий, 0 дублей
- ✅ **Новая категория «Сбалансированность рынка»** (`migration/005_market_balance.sql`): sort_order=11 (после «Спроса»); 9 индикаторов перенесены из `under_construction_domrf`; `under_construction_domrf` теперь содержит 3 видимые карточки
- ✅ **Подразделы в Спросе и Ценах** (`frontend/category.html`): добавлена константа `SUBSECTIONS`; рефакторинг render loop с извлечением `renderRow()`; CSS `.section-header`; обновлены `COMBO_OVERRIDES` для `under_construction_domrf` и `market_balance`
- ✅ Кнопки «Квартал/Год» на `chart.html` для квартальных показателей (1.2, 1.3) + загрузка official `.y`-companion
- ✅ period-toggle.js v4.0: удалён шим AnnualToggle, добавлен QoQ
- ✅ Миграция всех 37 комбо-страниц на единый `PeriodToggle.injectButtons`
- ✅ Annual companion-индикаторы (1.2.y, 1.3.y, миграция 003 + load_rosstat_annual.py)
- ✅ Новые комбо-страницы: housing-need-real-chart.html, housing-pace-real-chart.html

**Известные ограничения:**
- данные 2.13.ext только до 2015
- парсеры domclick.py и rosreestr.py не реализованы (6.28–6.34, 5.4)
- GitHub Actions для парсеров не создаются (fedstat блокирует облачные IP)
- domrf.py требует ручной загрузки файлов ДОМ.РФ через личный кабинет в `migration/domrf_data/`
- 2.6/2.7/2.8 не обновятся за 2026 год пока 1.1 за 2026-01-01 не появится в БД
- 6.35 — устаревший (14 точек до нояб 2022), нет парсера

## Agent skills

### Issue tracker

Задачи хранятся как локальные markdown-файлы под `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Стандартные пять ролей (needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: один `CONTEXT.md` + `docs/adr/` в корне репо. See `docs/agents/domain.md`.
