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

- **`data_service.py`** — все SQL-запросы к `data_points_with_dynamics`. `get_indicator_list_for_category` возвращает `IndicatorBrief` с last value, YoY, MoM. `get_time_series` — полный ряд с динамикой.
- **`export_service.py`** — генерация `.xlsx` через `openpyxl`. Используется для одиночного и мульти-экспорта.

`window.API_BASE = 'http://localhost:8001/api'` — задаётся в каждом HTML-файле явно.

## Frontend

### Три «системных» страницы

- **`index.html`** — сетка категорий + поиск (через `/api/categories` и `/api/search`)
- **`category.html`** — список показателей раздела. Содержит JS-константу `COMBO_OVERRIDES` — правила замены/добавления карточек на ссылки комбо-страниц (логика только во frontend, БД не меняется)
- **`chart.html`** — график одного показателя (`?code=6.1`). Поддерживает переключатели периода (1г/3г/5л/Всё), режима (Значения/г-г/м-м), таблицу, KPI-блок, блок «Связанные показатели»

### 26 комбо-страниц

Используют `/api/multi/data?codes=...`. Каждая содержит:
- Константы `CODES` (mapping имён в коды) и `LABELS` (подписи серий)
- Опционально `KEYS` (массив ключей для фильтров серий) — **обязательно объявлять после `LABELS`**
- Инициализацию `PeriodToggle.injectButtons(toolbar, ...)` или шим `AnnualToggle.injectAnnualBtn(...)`
- Горизонтальную панель фильтров серий

**Эталон разметки** горизонтальной панели фильтров: `subsidy-count.html`.

### JS-модули (`frontend/js/`)

| Файл | Назначение |
|------|-----------|
| `api.js` | `api.{categories,categoryIndicators,indicator,indicatorData,multiIndicatorData,...}` |
| `utils.js` | `fmtNum`, `fmtValue`, `fmtPct`, `fmtDate`, `fmtDateInline`, `deltaHtml`, `rangeStart`, `cleanName` |
| `sparkline.js` | Мини-графики для карточек на `category.html` |
| `chart-page.js` | Вся логика `chart.html` |
| `period-toggle.js` | **v3.1.** `PeriodToggle.aggregate`, `aggregateWavg`, `injectButtons`, `detectPeriodicity`. Содержит шим `window.AnnualToggle` для обратной совместимости со старыми страницами. |
| `annual-toggle.js` | Устаревший модуль; заменён `period-toggle.js` |

#### period-toggle.js: типы агрегации

| Тип | Применение |
|-----|-----------|
| `'sum'` | Ввод жилья, выдачи ипотек, счётные показатели |
| `'avg'` | Размер кредита, платёж, IHH, цены |
| `'wavg'` | Ставки и сроки — средневзвешенные по объёму выдач |

Страницы с `wavg` задают `window.AGG_TYPE = 'wavg'` и `window._WEIGHT_CODES = { код_ставки: код_объёма }` до загрузки `period-toggle.js`.

## Парсеры (`parsers/`)

Все парсеры наследуются от `BaseParser` (`parsers/base.py`). Шаблонный метод `run()`: подключение → `fetch_raw()` → `parse()` → `upsert_to_db()` → `REFRESH MATERIALIZED VIEW`. `upsert_to_db` использует `ON CONFLICT (indicator_id, period_date) DO UPDATE`.

| Парсер | Показатели | Расписание (GitHub Actions) |
|--------|-----------|------------------------------|
| `cbr.py` | 6.1–6.87 (ипотека) | Пн 06:00 UTC |
| `domrf.py` | 3.1–3.7, 4.1, 4.8–4.9 | Ежедневно 04:00 UTC |
| `rosstat.py` | 1.x, 2.1–2.13, 4.4–4.5 | Пн 06:30 UTC |

⚠️ `fetch_fedstat.py` и `migration/fetch_fedstat.py` — **только локально** (fedstat блокирует облачные IP, скорость ≤ 1 req/sec).

Локальная альтернатива расписанию: `parsers/scheduler.py` (APScheduler).

## Расчётные индикаторы (`migration/calc_*.py`)

Запускаются вручную; пишут результат напрямую в `data_points` и обновляют view.

| Код | Скрипт |
|-----|--------|
| `2.10` Обеспеченность жильём | `calc_housing_provision.py` |
| `3.5` Средняя площадь квартир | `calc_avg_apt_area.py` |
| `3.7` Девелоперская активность | `calc_developer_activity.py` |
| `5.3` Активность спроса | `calc_demand_activity.py` |
| `5.9`, `5.9.ma12` Темп продаж квартир | `calc_sales_pace.py` |
| `5.10` Доступность (зарплата/цена) | `calc_affordability.py` |
| `5.11` Доступность (ФЦП) | `calc_affordability_fcp.py` |
| `5.12–5.15 (.33/.38)` Потребность в жилье | `calc_housing_need.py` |
| `5.22`, `5.22.ma12` Темп продаж машиномест | `calc_sales_pace_mm.py` |

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
1. Кнопки «Квартал/Год» на `chart.html` для квартальных показателей (1.2, 1.3)
2. Деплой на VPS

**Известные ограничения:** данные 2.13.ext только до 2015; парсеры domclick.py и rosreestr.py не реализованы.

## Agent skills

### Issue tracker

Задачи хранятся как локальные markdown-файлы под `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Стандартные пять ролей (needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: один `CONTEXT.md` + `docs/adr/` в корне репо. See `docs/agents/domain.md`.
