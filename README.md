# Статистика рынка жилой недвижимости России

Публичный информационный сайт с интерактивными дашбордами по рынку жилой недвижимости России.
Проект собирает данные ЦБ РФ, Росстата/ЕМИСС, ДОМ.РФ и Росреестра, хранит их в PostgreSQL и отдаёт через FastAPI в статический frontend на ECharts.

## Текущий статус

- Backend и frontend реализованы и используются локально.
- Основная БД: PostgreSQL 16, база `realestate`.
- Локальные порты: backend `8001`, frontend `3000`.
- Frontend без Node.js и сборщика: обычные HTML/CSS/JS-файлы.
- Обновление данных выполняется локальными Python-парсерами и миграционными скриптами.
- GitHub Actions для парсеров не используются: часть источников блокирует облачные IP или требует локальных файлов.
- Продакшн-контур описан через Docker Compose: `db`, `backend`, `nginx`.

## Быстрый старт

```bash
# Активировать venv перед Python-скриптами
source venv/bin/activate

# Backend
cd backend
uvicorn app.main:app --reload --port 8001

# Frontend
cd frontend
python3 -m http.server 3000
```

Открыть:

- frontend: `http://localhost:3000`
- API: `http://localhost:8001/api/categories`
- Swagger: `http://localhost:8001/docs`

## Архитектура

```text
Источники данных
  ЦБ РФ, Росстат/ЕМИСС, ДОМ.РФ, Росреестр
    ↓
Python-парсеры и миграционные скрипты
    ↓
PostgreSQL 16
  sources / categories / indicators / data_points / update_jobs
  materialized view: data_points_with_dynamics
    ↓
FastAPI backend
    ↓
Vanilla HTML + CSS + JS + ECharts 5.4.3
```

## Структура репозитория

```text
backend/
  app/
    routers/       API-роуты
    services/      SQL-запросы и Excel-экспорт
    models.py      SQLAlchemy-модели
    schemas.py     Pydantic-схемы

frontend/
  index.html       главная страница категорий
  category.html    список показателей категории
  chart.html       одиночный график
  subsidy-purpose-structure.html  цели кредитования по льготным программам
  *.html           комбо-страницы и специальные графики
  css/             общие стили
  js/              API-клиент, форматирование, графики, периодичность

migration/
  001_init.sql     базовая схема БД
  00*_*.sql        последующие миграции
  calc_*.py        расчётные индикаторы
  fetch_*.py       загрузчики внешних источников
  migrate_*.py     загрузка локальных Excel/табличных файлов

parsers/
  base.py          общий шаблон парсера и инкрементальный upsert
  cbr.py           ЦБ РФ: ипотека, ИЖС, субсидии
  domrf.py         оркестратор локальных файлов ДОМ.РФ
  domrf_web.py     прямой web-парсер ЕИСЖС
  rosstat.py       обёртка над migration/fetch_fedstat.py
  scheduler.py     локальное расписание обновлений

nginx/
docker-compose.prod.yml
AGENTS.md
CLAUDE.md
PARSERS_PLAN.md
PROGRESS.md
```

## Backend

Стек: FastAPI, SQLAlchemy 2 sync, psycopg2, Pydantic v2.

Основные маршруты:

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/categories` | Список категорий |
| GET | `/api/categories/{code}/indicators` | Показатели категории |
| GET | `/api/indicators/{code}` | Метаданные показателя |
| GET | `/api/indicators/{code}/data` | Временной ряд |
| GET | `/api/indicators/{code}/data.xlsx` | Excel-экспорт одного показателя |
| GET | `/api/multi/data` | Несколько рядов для комбо-страниц |
| GET | `/api/multi/data.xlsx` | Excel-экспорт нескольких рядов |
| GET | `/api/search?q=` | Поиск |
| GET | `/api/meta/last-update` | Последнее обновление |

## Frontend

Три системные страницы:

- `index.html` — категории и поиск.
- `category.html` — карточки показателей, `COMBO_OVERRIDES`, подразделы `SUBSECTIONS`.
- `chart.html` — одиночный график, KPI, таблица, режимы “значения / г-г / м-м”, переключатель “Квартал / Год” для квартальных рядов.

Специальная страница:

- `subsidy-purpose-structure.html` — цели кредитования по льготным программам. Одна страница переключает программы, цели кредита, `Количество/Объём`, периодичность и режим динамики; данные берутся из скрытой сетки `6.52.x.x–6.57.x.x`, созданной `migration/009_subsidy_purpose_detail_v2.sql`.

Остальные HTML-файлы в `frontend/` — комбо-страницы и специальные графики. Они используют `/api/multi/data`, горизонтальную панель фильтров серий и общий модуль `frontend/js/period-toggle.js`.

В каждом HTML-файле API задаётся явно:

```js
window.API_BASE = 'http://localhost:8001/api'
```

## Данные

Основные таблицы:

| Таблица | Назначение |
|---|---|
| `sources` | Источники данных |
| `categories` | Тематические разделы |
| `indicators` | Метаданные рядов |
| `data_points` | Абсолютные значения по периодам |
| `update_jobs` | Лог запусков парсеров |

`data_points_with_dynamics` — materialized view с производными метриками YoY/MoM. После прямых ручных upsert-скриптов view нужно обновлять:

```bash
psql -U postgres -d realestate -c "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
```

Ключевые правила:

- `data_points` хранит только абсолютные значения.
- YoY/MoM считаются во view или во frontend-агрегации.
- Нет данных = `NULL`, не `0`.
- `period_date` — первый день периода.
- Для `unit='%'` динамика считается в процентных пунктах.
- `is_public=false` скрывает показатель из списков, но не из прямых API-запросов.

## Обновление данных

Парсеры запускаются локально:

```bash
source venv/bin/activate
cd parsers
python cbr.py --group primary
python cbr.py --group ihc
python domrf_web.py
python rosstat.py
```

`python cbr.py --group ihc` обновляет не только ИЖС и базовые субсидии, но и детальные цели кредитования из листа `01_02_03` ДОМ.РФ (`6.52.x.x–6.57.x.x`). Правило последнего периода: строки `Нет данных` по всем программам и метрикам должны быть `0` или пустыми.

Планировщик:

```bash
source venv/bin/activate
cd parsers
caffeinate -s nohup python scheduler.py > /tmp/scheduler.log 2>&1 &
tail -f /tmp/scheduler.log
```

Ключевые ограничения:

- `fedstat.ru` запускать только локально, скорость не выше 1 запроса/сек.
- `domrf.py` требует ручной загрузки файлов в `migration/domrf_data/`.
- `domrf_web.py` доступен только с российских IP.
- GitHub Actions для парсеров не создаются.

## Расписание

См. фактическое расписание в `parsers/scheduler.py`.

Коротко:

- 1-е число — ЦБ РФ, базовая ипотека.
- 5-е число — ДОМ.РФ web + средняя площадь квартир.
- 7-е число — ЦБ РФ ИЖС и субсидии.
- 20-е число — ДОМ.РФ файловый оркестратор и ежемесячный Росстат.
- 25-е число — обновление `indicator_update_map.xlsx`.
- 1 февраля / мая / августа / ноября — квартальные Росстат/Росреестр/доходы.
- 1 февраля, 15 марта, 5 июня — годовые companion- и расчётные показатели.

## Продакшн

Продакшн-конфигурация:

- `docker-compose.prod.yml`
- `nginx/nginx.conf`
- `.env.prod`

Контейнеры:

- `db`: PostgreSQL 16
- `backend`: FastAPI на порту `8000` внутри Docker-контура
- `nginx`: статика frontend и проксирование API

## Документация для разработки

- `AGENTS.md` — основной контекст для Codex и других coding agents.
- `CLAUDE.md` — такой же контекст для Claude Code.
- `PROGRESS.md` — исторический трекер выполненных блоков.
- `PARSERS_PLAN.md` — план восстановления парсеров; основные шаги уже реализованы, файл оставлен как справочник по решениям.
- `migration/004_db_audit_report.md` — аудит и чистка БД.

### Синхронизация agent-документов

`AGENTS.md` — источник правды. `CLAUDE.md` генерируется из него скриптом:

```bash
python3 scripts/sync_agent_docs.py
```

В репозитории есть pre-commit hook `.githooks/pre-commit`: если в коммит попал `AGENTS.md` или `CLAUDE.md`, hook обновляет `CLAUDE.md` из `AGENTS.md` и добавляет оба файла в индекс.
