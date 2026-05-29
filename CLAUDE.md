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
  → Python-парсеры и migration-скрипты (локальный scheduler / VPS)
  → PostgreSQL 16  (sources / categories / indicators / data_points)
  → FastAPI backend (порт 8001 локально, 8000 в Docker)
  → Vanilla HTML + ECharts 5.4.3 (без Node.js, без сборщика)
```

### Стек

- **Backend:** FastAPI + SQLAlchemy 2 (sync) + psycopg2 + Pydantic v2
- **Frontend:** HTML5 + CSS-переменные + Vanilla JS + ECharts 5.4.3 (CDN cdnjs)
- **Шрифты:** Playfair Display (заголовки), IBM Plex Sans (тело), IBM Plex Mono (числа)
- **Продакшн:** Docker Compose (db + backend + nginx), статика frontend через nginx

## Схема БД

Четыре основных таблицы + materialized view:

| Таблица | Назначение |
|---------|-----------|
| `sources` | Источники данных (ЦБ РФ, ДОМ.РФ и т.д.). Действующие коды: `cbr`, `domrf`, `rosstat`, `emiss`, `rosreestr`, `domclick`, `sberindex`, `calc` (расчётные индикаторы). |
| `categories` | Тематические разделы (mortgage_base, prices, demand …) |
| `indicators` | Метаданные временного ряда: `code`, `unit`, `periodicity`, `period_type`, `chart_type` |
| `data_points` | Только абсолютные значения: `(indicator_id, period_date)` — UNIQUE |
| `update_jobs` | Лог запусков парсеров: статус, кол-во upserted строк, ошибки |

**Materialized view `data_points_with_dynamics`** — все производные метрики (YoY, MoM через `LAG()`). Его надо обновлять после каждого upsert. Парсеры делают это автоматически (`BaseParser._refresh_view()`); ручной скрипт должен обновлять сам.

### Ключевые правила данных

- `data_points` хранит только абсолютные значения; YoY/MoM — только в `data_points_with_dynamics`
- Отсутствие данных = `NULL`, не `0` (ECharts рисует разрыв при `connectNulls: false`)
- `period_type`: четыре значения — `period` (за период: потоки — выдачи, ввод жилья, активность спроса 5.3), `period_start` (на начало отчётного периода: население 1.1, UC ДОМ.РФ, `uc_dev_activity`, ипотечный долг 6.19–6.27), `period_end` (на конец отчётного периода: жилфонд, потребность/скорость удовлетворения потребности 5.12–5.15, коэффициенты поглощения/запуска), `on_date` (на дату: квартирография, запасы стройки). Миграция `010_period_type_expansion.sql` и корректировки `012_metadata_row_updates.sql`; вспомогательная функция во frontend — `periodTypeLabel(type)` в `utils.js`
- YoY для `unit='%'` — абсолютная разность в п.п., не относительная
- `period_date` = первый день периода: 2024-01-01 = январь 2024 / год 2024
- `is_public=false` скрывает индикатор из списков разделов, но он доступен через `/api/multi/data` и прямые запросы
- `period_label` **обязательно** заполнять при любом upsert (формат: `'2025'` для годовых, `'Январь 2025'` для месячных). Пустой `period_label` приводит к пустому полю периода в таблице раздела

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

- **`index.html`** — сетка категорий + поиск (через `/api/categories` и `/api/search`). Счётчики карточек разделов считаются по тем же видимым карточкам, что и страницы разделов: главная загружает `/api/categories/{code}/indicators` и применяет `applyComboOverrides()`. Блок «Обновление данных» на главной не показывается.
- **`category.html`** — список показателей раздела. Использует `js/category-overrides.js` (`COMBO_OVERRIDES` + `applyComboOverrides`) — правила замены/добавления карточек на ссылки комбо-страниц (логика только во frontend, БД не меняется). Константа `SUBSECTIONS` задаёт подразделы (section-headers) внутри страниц отдельных категорий; коды в ней — это «эффективные» коды карточек после применения `COMBO_OVERRIDES`. Категории с подразделами: `demand` (5 групп), `prices` (2 группы), `mortgage_subsidy` (3 группы). Таблица раздела имеет 5 колонок (`Показатель`, `Последнее значение`, `Изм. г/г`, `Динамика`, `Источник`) и загружает данные для значений/спарклайнов/источников одним батчем через `/api/multi/data` с `rangeStart(5)`. Строки комбо с `_series` кликабельны и циклически переключают активную серию. Значение в колонке «Последнее значение» отображается числом в крупном моно-шрифте (без единиц); единицы с учётом масштаба (млн/млрд) — рядом с периодом через `·`. Функция `fmtValueSplit(v, unit, decimals?)` реализована инлайн в `category.html` и разделяет значение на числовую и единичную части; опциональный параметр `decimals` переопределяет автоматическую точность (приходит из `ind._decimals`). Для страниц-долей без реальных кодов в БД используется механизм `derivedSeries` (виртуальные серии, вычисляемые на фронте как отношение двух существующих рядов); при вычислении последнего значения trailing-нули пропускаются — берётся последняя ненулевая позиция числителя. Для виртуальных серий-сумм — поле `_sumCodes: [code, …]` в элементе `series` (код начинается с `__sum:`): компонентные коды добавляются в batch-запрос через `sumMeta`, сумма вычисляется поэлементно с выравниванием по дате на опорном (наидлиннейшем) ряду; `seriesCache` хранит `dates[]` для корректного выравнивания завершившихся рядов (например, Льготная ипотека).
- **`chart.html`** — график одного показателя (`?code=6.1`). Поддерживает переключатели периода (1г/3г/5л/Всё), режима (Значения/г-г/м-м), переключатель Квартал/Год для квартальных индикаторов, таблицу, KPI-блок, блок «Связанные показатели». Для квартальных показателей в режиме «Год» загружает official companion-индикатор `<code>.y` (если существует) вместо агрегации кварталов. **Метастрока** под заголовком содержит два элемента: источник данных и тип данных (`periodTypeLabel(indicator.period_type)`, заполняется `chart-page.js`). Единица измерения и дата публикации в метастроке не отображаются. На всех комбо-страницах метастрока устроена аналогично: тип данных заполняет `combo-page.js` / `subsidy-purpose-page.js` из первого индикатора в ответе API. Таблицы исходных данных в `chart-page.js`, `combo-page.js` и `subsidy-purpose-page.js` следуют общему правилу: единица измерения добавляется только в заголовок столбца значения, сами значения идут без единиц; заголовки столбцов динамики не содержат `%`/`п.п.`, единицы динамики показываются рядом со значениями в ячейках. Для годовой агрегации столбец динамики периода (`м/м` или `кв./кв.`) скрывается.

### Комбо-страницы и специальные графики

В `frontend/` кроме трёх системных страниц лежат комбо-страницы и специальные графики. Большинство используют `/api/multi/data?codes=...`. Каждая содержит:
- Константы `CODES` (mapping имён в коды) и `LABELS` (подписи серий)
- Опционально `KEYS` (массив ключей для фильтров серий) — **обязательно объявлять после `LABELS`**
- Инициализацию через `ComboPage.init({ codes, labels, keys, ... })`; `PeriodToggle` подключается внутри `ComboPage`, если страница не `pointInTime`, `annualOnly` или `quarterlyOnly`. `ComboPage.init()` возвращает `{ cfg, state, rebuild }` для страниц с собственными переключателями, которым надо менять `cfg.valueCode`, `unit` или `fileName` и затем вызывать `rebuild()`.
- Горизонтальную панель фильтров серий

**`share-chart.html`** — структура ввода жилья МЖС/ИЖС. Месячные доли считаются на фронте из сырых рядов `2.2` (ИЖС) и `2.3` (МЖС): `доля = компонент / (2.2 + 2.3) × 100`. Для квартала и года нельзя агрегировать уже посчитанные месячные проценты через `sum`/`avg`; страница использует `ComboPage.aggregateSeries`, где сначала суммируются исходные объёмы `2.2` и `2.3` за полный период (3/12 месяцев), затем считается доля от суммарного ввода. Динамика для долей — разность в п.п.

**`ihh-chart.html`** — средний и медианный ИХХ (`3.18`, `3.19`) являются снимковыми индексами, поэтому страница задаёт `pointInTime: true`: переключатель `Месяц/Квартал/Год` не показывается и агрегация не выполняется. Для line-графика также задаётся `stackBars: false`, чтобы tooltip не показывал строку «Итого» и ничего не суммировал.

**`subsidy-purpose-structure.html`** — специальная страница целей кредитования по льготным программам. Использует модуль `js/subsidy-purpose-page.js`, а не `ComboPage`: одна HTML-страница переключает 6 программ внутри страницы (`Все`, `Льготная`, `Семейная`, `ДВ и Арктика`, `IT`, `Отдельные регионы`), метрику `Количество/Объём`, периодичность и цели кредита. Источник — лист `01_02_03` файла ДОМ.РФ «Статистические ряды»; коды новой сетки `6.52.x.x–6.57.x.x`, созданные миграцией `009_subsidy_purpose_detail_v2.sql`. На Семейной ипотеке вторичка отображается двумя отдельными целями, как в первоисточнике.

Все страницы раздела `mortgage_subsidy` в метастроке, подписи под графиком и footer показывают источник `ДОМ.РФ`; в БД все индикаторы этой категории также должны иметь `source_id=domrf` (см. `012_metadata_row_updates.sql`).

**`subsidy-family-types.html`** — комбо-страница типов семей в Семейной ипотеке. В фильтре серий остаются только 3 типа семьи (`До 7 лет`, `7–18 лет`, `Инвалидность`), а метрика `Количество/Объём` переключается отдельной группой кнопок в тулбаре. Эта группа должна идти после автоматически внедряемого `PeriodToggle` (`Месяц/Квартал/Год`), поэтому страница переставляет её после `ComboPage.init()`. KPI-плашки показывают те же 3 типа семьи и обновляются через `onData`/`renderKpis`; при переключении метрики надо менять текущую метрику, `cfg.valueCode`, `unit`, `sfx`, `fileName` и затем вызывать `rebuild()`. Хвост нулевых месяцев обрезается через `trimToNonZeroDateCodes: Object.values(CODES)`, чтобы ось, KPI и таблица заканчивались последним месяцем с реальными значениями.

**Эталон разметки** горизонтальной панели фильтров: `subsidy-count.html`.

Для страниц, где последний отображаемый период должен существовать сразу у нескольких обязательных серий, используйте `trimToCommonDateKeys` (или `trimToCommonDateCodes`) в `ComboPage.init()`. Настройка обрезает все ряды после последней общей непустой даты этих серий перед отрисовкой KPI, графика и таблицы. Если API содержит технические нули в хвосте и их нельзя показывать как актуальный период графика, используйте `trimToNonZeroDateKeys`/`trimToNonZeroDateCodes`: они ищут последнюю общую дату, где обязательные ряды не равны `0`. На subsidy-страницах характеристик кредита обязательные действующие программы: `semya`, `dv`, `it`, `regions`; завершённую `lgota` не включать в отсечку.

Подписи горизонтальной оси всех `chart.html`, `ComboPage`-страниц и `subsidy-purpose-page.js` строятся через общие helpers из `utils.js`: `formatXAxisLabel`, `xAxisLabelInterval`, `cleanAxisLabel`. Месячные двухстрочные подписи пишутся без точки после сокращения месяца (`янв\n2026`). Плотность и интервал подписей контролируются только helper-ом `xAxisLabelInterval`, а не `hideOverlap` ECharts (`hideOverlap: false`).

`xAxisLabelInterval(total, periodicity)` возвращает объект `{ interval, showMinLabel, showMaxLabel }` для `axisLabel`. **Главный принцип: между всеми подписями строго одинаковое расстояние** (= шаг), и последний период всегда подписан. Алгоритм: выбирается наименьший **круглый** шаг из кандидатов (месяцы `1/2/3/6/12`, кварталы `1/2/4/8`, годы `1/2/5/10`), при котором число подписей не превышает комфортного максимума (≈ 20 / 16 / 12 соответственно); затем строится равномерная сетка с привязкой к **правому** краю: `offset = lastIndex % step`, метки на `offset, offset+step, …, lastIndex`. Это даёт идеально равные промежутки и подписанный последний период; слева возможен небольшой отступ `offset` (первая подпись на 1–N-м периоде — это допустимая плата за равные промежутки). `showMinLabel` и `showMaxLabel` **всегда `true`**: при `false` ECharts гасит первую/последнюю ВЫБРАННУЮ interval-ом метку у края (даже если это не индекс 0), из-за чего слева образуется большая пустота; при `true` состав меток полностью определяет `interval`, а индекс 0 при `offset > 0` не форсируется (проверено на квартальном «всё время»). При `step ≤ 1` возвращается `interval: 0` (показать все подписи). **Прим.:** для квартальных индикаторов в режиме «Год» (`chart.html`) `effPeriodicity` остаётся `quarterly` (берётся из базового индикатора), поэтому годовой companion-ряд классифицируется по квартальным порогам — это не ломает равномерность.

### JS-модули (`frontend/js/`)

| Файл | Назначение |
|------|-----------|
| `api.js` | `api.{categories,categoryIndicators,indicator,indicatorData,multiIndicatorData,...}` |
| `utils.js` | `fmtNum`, `fmtValue`, `fmtPct`, `fmtDate`, `fmtDateInline`, `formatXAxisLabel`, `xAxisLabelInterval`, `cleanAxisLabel`, `deltaHtml`, `rangeStart`, `cleanName`, `periodTypeLabel` |
| `category-overrides.js` | Общие правила `COMBO_OVERRIDES` и `applyComboOverrides()` для видимых карточек категорий. Подключается на `index.html` и `category.html`, чтобы счётчики главной совпадали со страницами разделов. Каждая запись `COMBO_OVERRIDES` содержит поле `series: [{code, label}, …]` — массив реальных серий для цикличного переключения значений в таблице (первый элемент = `_sparkCode`). Опциональное поле `decimals: N` задаёт точность числа в колонке «Последнее значение» (переопределяет автоматическую логику `fmtValueSplit`); propagates в `ind._decimals` и `row.dataset.seriesDecimals`. Для страниц-долей без собственных кодов в БД — поле `derivedSeries: [{code, label, numerator, denominator}, …]`: виртуальные серии с `__`-префиксом кода, вычисляемые на фронте как `numerator / denominator × 100`. Для серий-сумм без собственного кода в БД — поле `_sumCodes: [code, …]` в элементе `series` (виртуальный `code` начинается с `__sum:`): `category.html` добавляет компоненты в batch и вычисляет сумму через `sumMeta`. Хелпер `_buildEffectiveSeries(rule)` возвращает `derivedSeries` (если задано) или `series`; `applyComboOverrides()` записывает результат в `_series` каждого индикатора. |
| `sparkline.js` | Мини-графики для карточек на `category.html` |
| `chart-page.js` | Вся логика `chart.html`. Для квартальных показателей автоматически пытается загрузить companion-индикатор `<code>.y` (официальный годовой ряд из Росстата). |
| `combo-page.js` | Общий модуль многоcерийных страниц: загрузка `/api/multi/data`, фильтр серий, KPI/table hooks, агрегация через `PeriodToggle`, `preProcess`, кастомная агрегация через `aggregateSeries(key, raw, periodicity, allData)`, `trimToCommonDateKeys`/`trimToCommonDateCodes`, `trimToNonZeroDateKeys`/`trimToNonZeroDateCodes`; `init()` возвращает управляющий объект `{ cfg, state, rebuild }` для страниц с дополнительными переключателями. |
| `subsidy-purpose-page.js` | Специальная логика страницы `subsidy-purpose-structure.html`: переключение программ, целей кредита, метрики `Количество/Объём`, KPI, график, таблица и выгрузки для кодов `6.52.x.x–6.57.x.x`. |
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

Система парсинга уже переработана по плану из `PARSERS_PLAN.md`. Файл оставлен как справочник по исходным проблемам и принятым решениям.

Все парсеры наследуются от `BaseParser` (`parsers/base.py`). Шаблонный метод `run()`: подключение → `fetch_raw()` → `parse()` → фильтр новых периодов → `upsert_to_db()` → `REFRESH MATERIALIZED VIEW`.

**Принцип инкрементального обновления**: `upsert_to_db` использует `ON CONFLICT DO NOTHING`; перед upsert отфильтровываются записи с `period_date ≤ MAX(period_date)` в БД для каждого индикатора — существующие данные не перезаписываются. Для рядов, которые ретроспективно уточняются, есть отдельный `upsert_update_to_db()`.

| Парсер | Показатели | Статус | Реальный источник |
|--------|-----------|--------|-------------------|
| `cbr.py` | 6.1–6.87 (ипотека, ИЖС, субсидии, цели кредитования `6.52.x.x–6.57.x.x`) | ✅ Переписан; `group='primary'/'ihc'` | CBR Excel + ДОМ.РФ API по субсидиям |
| `domrf.py` | 3.x, 4.1, 4.8–4.9, 5.x (DomRF) | ✅ Файловый оркестратор | Локальные Excel в `migration/domrf_data/`, обработка через `migrate_*.py` |
| `domrf_web.py` | 3.1–3.4, 3.17–3.19 (ЕИСЖС) | ✅ Готов | Скачивает `01_01_stockvariablesexsales.xlsx` с наш.дом.рф напрямую |
| `rosstat.py` | 1.x, 2.x, 4.4–4.5, 5.1 | ✅ Обёртка над `fetch_fedstat.py` | `migration/fetch_fedstat.py` (POST-запросы к fedstat.ru) |

**Рабочие компоненты**:
- `migration/fetch_fedstat.py` — FedstatClient с корректными EMISS IDs и payload для 1.2, 1.3, 2.1, 2.2, 2.3, 2.9, 2.11, 2.12, 2.13, 2.13.ext, 4.4, 4.5, 5.1. Запускать: `python migration/fetch_fedstat.py [код ...]`
- `migration/migrate_apartments.py`, `migrate_matrix_projects.py`, `migrate_sales_matrix.py` — обработка файлов DomRF
- `migration/migrate_subsidy_update.py` и `migration/migrate_subsidy_detail.py` — субсидии и детализация. `migrate_subsidy_detail.py` грузит новую сетку целей кредитования `6.52.x.x–6.57.x.x` из листа `01_02_03`; старые `6.52.1–6.57.3` остаются legacy-рядами.

⚠️ fedstat.ru — **только локально** (облачные IP блокируются, скорость ≤ 1 req/sec). GitHub Actions для парсеров не создаются.

**Расписание** (`parsers/scheduler.py`, APScheduler):

*Ежемесячно:*
- 1-е,  08:00 UTC — `day1_cbr_primary`: CBR 6.1–6.27 (ипотека, 02_02/02_03)
- 5-е,  08:00 UTC — `day5_domrf_web`: DomRF Web (3.1–3.4, 3.17–3.19) + calc_avg_apt_area (3.5); retry +5д
- 7-е,  08:00 UTC — `day7_cbr_ihc`: CBR ИЖС + субсидии 6.36–6.87, включая детальные цели кредитования `6.52.x.x–6.57.x.x` (02_41 + ДОМ.РФ API)
- 20-е, 10:00 UTC — `day20_domrf`: DomRF оркестратор + calc_affordability (5.10/5.11); retry +5д
- 20-е, 11:00 UTC — `monthly_rosstat`: Rosstat 2.1/2.2/2.3 + calc_housing_per_capita (2.6–2.8); retry +5д
- 25-е, 12:00 UTC — `monthly_status_update`: обновляет indicator_update_map.xlsx (Актуальный период + Статус)

*Ежеквартально (1 фев / 1 май / 1 авг / 1 ноя):*
- `quarterly_rosstat`: Rosstat 1.3/4.4/4.5 + fetch_rosreestr_ddu (5.1) + fetch_income_rosstat (1.2 + 1.2.y)

*Ежегодно:*
- 1 фев,  08:30 UTC — `annual_companion`: calc_annual_companion (1.3.y); retry 1-е кажд. мес.
- 15 мар, 08:00 UTC — `annual_population_dev`: migrate_population (1.1) + calc_developer_activity (3.7, uc_dev_activity) + calc_demand_activity (5.3); retry 15-е кажд. мес.
- 5 июн,  08:00 UTC — `annual_housing_stats`: Rosstat 2.9/2.11/2.12/2.13 → calc_housing_provision (2.10) → calc_housing_need (5.12–5.15); retry +10д

Все job'ы с retry проверяют `MAX(period_date)` в БД после каждого запуска и добавляют one-shot повтор если данных нет. `CBRParser(group=...)` принимает `'primary'` или `'ihc'`. `RosstatParser(codes=[...])` принимает список кодов для fetch_fedstat.py.

DomRF требует ручной загрузки файлов в `migration/domrf_data/`.

⚠️ `domrf_web.py` доступен только с российских IP (ЕИСЖС геоблокирует зарубежные запросы).

**CBR-конвенция дат**: колонка `01.02.2026` в Excel = данные **за январь 2026** (дата отчёта = первое число следующего месяца). При парсинге: `period_date = date(YYYY, MM-1, 1)`.

## Annual companion-индикаторы (суффикс `.y`)

Companion-индикаторы хранят **годовое** значение для квартальных рядов — отображаются на `chart.html` в режиме «Год». `periodicity='annual'`, `is_public=false`. Миграция: `migration/003_annual_companion_indicators.sql`.

| Код | Название | Способ обновления |
|-----|---------|-------------------|
| `1.2.y` | Среднедушевые доходы населения (годовые) | **Авто**: `fetch_income_rosstat.py` (строка «Год» из xlsx, quarterly_rosstat 1 фев/май/авг/ноя) |
| `1.3.y` | Среднемесячная зарплата (годовая) | **Авто**: `calc_annual_companion.py` (avg Q1–Q4 из 1.3, annual_companion 1 фев + retry) |

Companion-индикаторы обновляются автоматически в scheduler:

- **1.2 + 1.2.y** — `fetch_income_rosstat.py`: скачивает `urov_10kv_Nkv-YYYY.xlsx` с rosstat.gov.ru/folder/13397; квартальные строки → `1.2`; строка «Год» → `1.2.y` (официальное годовое среднее Росстата). Запускается в `quarterly_rosstat` (4 раза в год).
- **1.3.y** — `calc_annual_companion.py`: `(Q1+Q2+Q3+Q4) / 4` из квартальных данных `1.3`. Запускается в `annual_companion` (1 февраля + retry на 1-е число кажд. мес. если данных нет).

## Детализация целей кредитования субсидий

Миграция `migration/009_subsidy_purpose_detail_v2.sql` создаёт скрытые индикаторы для листа `01_02_03` файла ДОМ.РФ «Статистические ряды».

Сетка кодов:

| Уровень | Значение |
|---------|----------|
| `6.52` | Все программы |
| `6.53` | Льготная ипотека |
| `6.54` | Семейная ипотека |
| `6.55` | Дальневосточная и арктическая ипотека |
| `6.56` | IT ипотека |
| `6.57` | Ипотека в отдельных регионах |
| `.1–.6` | Цель кредита: ДДУ, ДКП у застройщика, ИЖС, готовый ИЖД, вторичка; у Семейной `.5` = вторичка в городах без стройки, `.6` = вторичка прочее |
| `.1/.2` | Метрика: количество (`шт.`) / объём (`млн руб.`) |

Пример: `6.54.5.2` = Семейная ипотека / вторичка в городах без стройки / объём.

Период включается в загрузку только если по всем 6 программам и обеим метрикам строки `Нет данных` на листе `01_02_03` равны `0` или пустые. Внутри валидного периода пустая ячейка остаётся `NULL`, числовой `0` остаётся нулём. `parsers/cbr.py --group ihc` обновляет эти ряды автоматически через `day7_cbr_ihc` с перезаписью последних 36 завершённых месяцев; ручная загрузка — через `migration/migrate_subsidy_detail.py`.

## Расчётные индикаторы (`migration/calc_*.py`)

Пишут результат напрямую в `data_points` и обновляют view.

**В составе scheduler (автоматически):**

| Код | Скрипт | Триггер (job) |
|-----|--------|---------------|
| `1.3.y` Зарплата годовая | `calc_annual_companion.py` | `annual_companion` (1 фев + retry) |
| `2.6`, `2.7`, `2.8` Ввод жилья на душу | `calc_housing_per_capita.py` | `monthly_rosstat` (20-е + retry) |
| `2.10` Обеспеченность жильём | `calc_housing_provision.py` | `annual_housing_stats` (5 июн + retry) |
| `3.5` Средняя площадь квартир | `calc_avg_apt_area.py` | `day5_domrf_web` (5-е + retry) |
| `3.7`, `uc_dev_activity` Девелоперская активность | `calc_developer_activity.py` | `annual_population_dev` (15 мар + retry) |
| `5.3` Активность спроса | `calc_demand_activity.py` | `annual_population_dev` (15 мар + retry) |
| `5.9`, `5.9.ma12` Темп продаж квартир | `calc_sales_pace.py` | `day20_domrf` (через domrf.py, 20-е) |
| `5.10` Доступность (зарплата/цена) | `calc_affordability.py` | `day20_domrf` (20-е + retry) |
| `5.11` Доступность (ФЦП) | `calc_affordability_fcp.py` | `day20_domrf` (20-е + retry) |
| `5.12–5.15 (.33/.38)` Потребность в жилье / скорость удовлетворения потребности | `calc_housing_need.py` | `annual_housing_stats` (после calc_housing_provision) |
| `5.22`, `5.22.ma12` Темп продаж машиномест | `calc_sales_pace_mm.py` | `day20_domrf` (через domrf.py, 20-е) |

**Ручной запуск:** все показатели обновляются автоматически. `load_rosstat_annual.py` оставлен как инструмент отладки, в scheduler не используется.

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
3. Проверить dry-run / ручной запуск обновлённых парсеров на локальной БД и зафиксировать результаты в `indicator_update_map.xlsx`

**Недавно завершено:**
- ✅ **Метастрока: источник + тип данных** (`migration/010_period_type_expansion.sql`, `migration/012_metadata_row_updates.sql`, `frontend/js/utils.js`, `frontend/chart.html`, `frontend/js/chart-page.js`, `frontend/js/combo-page.js`, `frontend/js/subsidy-purpose-page.js`, все 46 комбо-HTML): `period_type` расширен до 4 значений (`period`, `period_start`, `period_end`, `on_date`); бывшие `point_in_time` индикаторы реклассифицированы. Метастрока на всех страницах теперь показывает источник + тип данных (вместо даты публикации + источника + единицы). Важные корректировки: `1.1` и `uc_dev_activity` = `period_start`, `5.12–5.15` = `period_end`, `5.3` = `source=calc`, `mortgage_subsidy` = `source=domrf`. Функция `periodTypeLabel(type)` добавлена в `utils.js`.
- ✅ **`_sumCodes` в COMBO_OVERRIDES** (`frontend/js/category-overrides.js`, `frontend/category.html`): механизм виртуальных серий-сумм — `{ code: '__sum:…', label: '…', _sumCodes: ['6.36', …] }` в поле `series`. Компонентные коды добавляются в batch-запрос через `sumMeta`, сумма вычисляется с выравниванием по дате на опорном ряду (наидлиннейший), YoY — через позицию −12. `seriesCache` дополнен полем `dates[]` для выравнивания завершившихся рядов. Применено к «Количество кредитов» и «Объём кредитов» раздела `mortgage_subsidy` (серия «Все программы»).
- ✅ **Источник `mortgage_subsidy`** (БД + frontend): все индикаторы категории `mortgage_subsidy` переведены на `source=domrf`; ДОМ.РФ является первичным публикатором статистики по субсидированным программам ипотеки. Статические метастроки/подписи на `subsidy-*.html` также должны показывать `ДОМ.РФ`.
- ✅ **`derivedSeries` в COMBO_OVERRIDES** (`frontend/js/category-overrides.js`, `frontend/category.html`): механизм виртуальных серий-долей, вычисляемых на фронте как `numerator / denominator × 100`. Виртуальные коды имеют префикс `__`; API-батч их пропускает, вычисление происходит после загрузки реальных рядов. Применено к страницам «Структура ввода жилья», «Семейная ипотека: типы семей», «Уровень/Скорость потребности» — все ранее «пустые» (`series: []`) карточки теперь показывают значения и спарклайны.
- ✅ **Доработка таблицы категорий** (`frontend/category.html`): `fmtValueSplit(v, unit)` разделяет значение на числовую часть (крупный моно-шрифт) и единицы с масштабом (рядом с периодом через `·`), устраняя визуальное расхождение между комбо- и обычными строками; источник выровнен по правому краю.
- ✅ **Единые правила таблиц исходных данных** (`frontend/js/chart-page.js`, `frontend/js/combo-page.js`, `frontend/js/subsidy-purpose-page.js`, `subsidy-*.html` и специальные combo HTML): единицы измерения значений показываются только в заголовке столбца, строки значений без единиц; единицы динамики (`%`/`п.п.`) показываются в ячейках динамики, но не в заголовках.
- ✅ **`series[]` в COMBO_OVERRIDES** (`frontend/js/category-overrides.js`): добавлено поле `series: [{code, label}, …]` ко всем 46 записям; `applyComboOverrides()` теперь выдаёт `_series` и автоматически выводит `_sparkCode` из `series[0].code`. Уточнены фактические коды из БД: 6.7–6.12 = первичный рынок ипотеки, 6.13–6.18 = вторичный; 6.76 = строительство ИЖС, 6.82 = покупка готового ИЖС; 3.17 = количество групп застройщиков, 3.18 = HHI.
- ✅ **Таблица раздела с источником и batch-загрузкой** (`frontend/category.html`): добавлена 5-я колонка «Источник»; значения, YoY, источники и спарклайны загружаются одним `api.multiIndicatorData()` вместо N запросов; строки комбо с `_series` переключают серию по клику с обновлением значения, периода, YoY, подписи, точек и спарклайна.
- ✅ **Страница целей кредитования по льготным программам** (`frontend/subsidy-purpose-structure.html`, `frontend/js/subsidy-purpose-page.js`, `migration/009_subsidy_purpose_detail_v2.sql`): одна страница с переключением 6 программ, метрики `Количество/Объём`, KPI, графиком и таблицей; данные листа `01_02_03` заведены в новой скрытой сетке `6.52.x.x–6.57.x.x`; `cbr.py --group ihc` и `migrate_subsidy_detail.py` обновляют эту сетку по правилу строк `Нет данных`.
- ✅ **Переработка системы парсинга** (`PARSERS_PLAN.md`): `base.py` переведён на инкрементальный upsert; `cbr.py` переписан под реальные файлы CBR и группы `primary`/`ihc`; `fetch_fedstat.py` расширен новыми EMISS-индикаторами; `rosstat.py` и `domrf.py` стали оркестраторами.
- ✅ **Новое расписание парсеров** (`parsers/scheduler.py`): 3 job'а → 10 job'ов; полная retry-логика (проверка БД после каждого запуска); `CBRParser(group='primary'/'ihc')`; `RosstatParser(codes=[...])`; удалён `SubsidyOnlyParser`; добавлен `monthly_status_update` (25-е)
- ✅ **Мониторинг обновлений** (`migration/update_indicator_status.py`): скрипт читает `MAX(period_date)` из БД, вычисляет ожидаемый период по расписанию, проставляет «Актуальный период» и «Статус» (✅/⏳/⚠️/⛔) в `indicator_update_map.xlsx`; запускается автоматически 25-е числа
- ✅ **Аудит обновления индикаторов** (`migration/generate_update_map.py`, `indicator_update_map.xlsx`): полная карта 157 индикаторов с цветовой разметкой; исправлены найденные проблемы:
  - Удалены 6.46–6.67.1 (ЦБ РФ ДДУ — 25 индикаторов без источника обновления) + `mm_count`/`mm_area` → `migration/006_delete_cbr_ddu_indicators.sql`
  - `migrate_sales_matrix.py` — изменены коды `mm_count`→`5.20`, `mm_area`→`5.21` (исправлен разрыв в цепочке 5.20→5.22)
  - Создан `calc_housing_per_capita.py` (2.6/2.7/2.8 = ввод/население); добавлен в scheduler после rosstat.py
- ✅ **`parsers/domrf_web.py`** — готовый парсер: скачивает `01_01_stockvariablesexsales.xlsx` с наш.дом.рф, обновляет 3.1, 3.2, 3.3, 3.4, 3.17, 3.18, 3.19 (77 месяцев, 2020–2026); идемпотентен (повторный запуск → 0 новых строк); зарегистрирован в `scheduler.py` как `day5_domrf_web`
- ✅ **Аудит системы парсинга**: выявлены причины, почему старые парсеры не работали; составлен и затем реализован план переработки (`PARSERS_PLAN.md`); установлены зависимости (`requests`, `bs4`, `APScheduler` в venv)
- ✅ **Главная страница и счётчики разделов** (`frontend/index.html`, `frontend/js/category-overrides.js`): блок «Обновление данных» убран; правила `COMBO_OVERRIDES` вынесены из `category.html` в общий модуль, и главная считает количество показателей через те же видимые карточки, что страницы разделов
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

### Agent docs sync

`AGENTS.md` — источник правды. `CLAUDE.md` генерируется из него через `python3 scripts/sync_agent_docs.py`. Перед коммитом tracked hook `.githooks/pre-commit` синхронизирует и добавляет оба файла в индекс, если один из них попал в коммит.

### Issue tracker

Задачи хранятся как локальные markdown-файлы под `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Стандартные пять ролей (needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: один `CONTEXT.md` + `docs/adr/` в корне репо. See `docs/agents/domain.md`.
