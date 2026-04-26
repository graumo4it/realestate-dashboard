# PROGRESS.md — Трекер разработки
## Дашборд «Статистика рынка жилой недвижимости России»

> Последнее обновление: апрель 2026
> Ветка разработки: `v1.1-improvements`
> Backend: порт **8001** | Frontend: порт **3000**
> Путь: `/Users/egor/Работа/data hub/realestate-dashboard/`

---

## Быстрый запуск

```bash
# Backend
cd /Users/egor/Работа/data\ hub/realestate-dashboard/backend
uvicorn app.main:app --reload --port 8001

# Frontend (фоновый режим)
cd /Users/egor/Работа/data\ hub/realestate-dashboard/frontend
nohup python3 -m http.server 3000 > /tmp/frontend.log 2>&1 &

# Остановить frontend
lsof -ti:3000 | xargs kill -9
```

---

## Статус по исходному плану ТЗ

| # | Задача | Статус | Файлы |
|---|--------|--------|-------|
| 1 | Структура репозитория, .gitignore, README | ✅ | `.gitignore`, `README.md` |
| 2 | Схема БД (DDL + materialized view) | ✅ | `migration/001_init.sql` |
| 3 | Скрипт миграции Excel → БД | ✅ | `migration/excel_to_db.py` |
| 4 | FastAPI backend (все эндпоинты) | ✅ | `backend/app/` |
| 5 | Проверка API | ✅ | — |
| 6 | Frontend: index.html + chart.html | ✅ | `frontend/index.html`, `frontend/chart.html` |
| 7 | Frontend: category.html | ✅ | `frontend/category.html` |
| 8 | Парсер ЦБ РФ | ✅ | `parsers/cbr.py` |
| 9 | Парсеры ДОМ.РФ, Росстат | ✅ | `parsers/domrf.py`, `parsers/rosstat.py` |
| 10 | GitHub Actions (CI + расписание парсеров) | ✅ | `.github/workflows/` |
| 11 | Продакшн (VPS + Docker) | ⏳ | `docker-compose.prod.yml` |
| 12 | Автодеплой при push в main | ✅ | `.github/workflows/deploy.yml` |

---

## Блок правок v1.1

### Блок 1 — Улучшения chart-page ✅

| Задача | Файл |
|--------|------|
| MoM в backend (п.п. для %, % для остальных) | `services/data_service.py` |
| MoM во frontend | `js/chart-page.js` |
| Кнопки ретроспективы 1г/3г/5л — от последней точки данных | `js/chart-page.js` |
| `cleanName()` — очистка названий от кодов | `js/utils.js` |
| Кнопка «За всё время» | `js/chart-page.js` |
| Объединены плашки «Последнее значение» и «Период» | `chart.html` |
| Ползунок временной шкалы (ECharts dataZoom) | `js/chart-page.js` |
| Панель фильтров в сайдбаре | `chart.html`, `css/chart.css` |
| Исправлены единицы измерения ~20 индикаторов | SQL в БД |
| Скрыты: 5.4, разделы Домклик/Frank RG, ряд 6.xx | SQL `is_public=false` |
| Типы графиков: 5.20, 5.8 → bar | SQL `chart_type='bar'` |
| п.п. для процентных, xData из `p.label`, кв./кв. для quarterly | `js/chart-page.js` |
| Заголовок таблицы: «Значение, {unit}» | `js/chart-page.js` |

### Блок 2 — Данные из fedstat.ru ✅

Скрипт: `migration/fetch_fedstat.py`
⚠️ Запускать только локально — fedstat блокирует облачные IP

| Код | Индикатор | Точек | Период |
|-----|-----------|-------|--------|
| `2.9` | Жилфонд | 18 | 2008–2025 |
| `2.11` | Прибыло жилфонда | 17 | 2008–2025 |
| `2.12` | Выбыло жилфонда | 18 | 2008–2025 |
| `2.13.ext` | Доля ветхого жилья | 10 | 2006–2015 |
| `1.2` | Среднедушевые доходы (quarterly) | 56 | 2012–2025 |
| `1.3` | Зарплата (quarterly) | 35 | 2017–2025 |
| `1.1` | Население | — | ❌ fedstat/31557 недоступен |

### Блок 3 — Расчётные индикаторы ⏳

| Код | Формула | Статус |
|-----|---------|--------|
| `2.10` Обеспеченность жильём | 2.9 / 1.1 × 1000 | ⏳ |
| `5.9` Темп продаж | 5.8 / 3.1 × 100% | ⏳ |
| `5.10` КДЖ | цена 54 кв.м / доход семьи | ⏳ |
| `5.11` Доступность по ипотеке | платёж < 50% дохода | ⏳ |
| `5.12–5.15` Потребность в жилье | методика ДОМ.РФ | ⏳ |

### Блок 4 — Комбо-страницы ✅

Все 20 файлов созданы в `frontend/`. Навигационная увязка — **Блок 6 (текущая задача)**.

| Файл | Индикаторы | Тип графика |
|------|-----------|-------------|
| `combo-chart.html` | 2.2, 2.3 | bar stacked (МЖС+ИЖС) |
| `share-chart.html` | 2.2, 2.3 | bar 100% (структура %) |
| `ihh-chart.html` | 3.18, 3.19 | line (ИХХ средний+медианный) |
| `prices-chart.html` | 4.4.x, 4.5.x | line, двухуровневые вкладки |
| `mortgage-count.html` | 6.7, 6.13, 6.1 | bar stacked |
| `mortgage-volume.html` | 6.8, 6.14, 6.2 | bar stacked |
| `mortgage-rate.html` | 6.3, 6.9, 6.15 | line, п.п. |
| `mortgage-term.html` | 6.4, 6.10, 6.16 | line |
| `mortgage-size.html` | 6.5, 6.11, 6.17 | line |
| `mortgage-payment.html` | 6.6, 6.12, 6.18 | line |
| `subsidy-count.html` | 6.36, 6.38, 6.40, 6.42 | bar stacked |
| `subsidy-volume.html` | 6.37, 6.39, 6.41, 6.43 | bar stacked |
| `subsidy-ddu-count.html` | 6.46, 6.48, 6.50, 6.52 | bar stacked |
| `subsidy-ddu-volume.html` | 6.47, 6.49, 6.51, 6.53 | bar stacked |
| `igs-count.html` | 6.70, 6.76, 6.82 | bar stacked |
| `igs-volume.html` | 6.71, 6.77, 6.83 | bar stacked |
| `igs-rate.html` | 6.72, 6.78, 6.84 | line, п.п. |
| `igs-term.html` | 6.73, 6.79, 6.85 | line |
| `igs-size.html` | 6.74, 6.80, 6.86 | line |
| `igs-payment.html` | 6.75, 6.81, 6.87 | line |

### Блок 5 — Форматирование данных в БД ✅

Применено в локальной БД. Дополнительные миграции:
- `migration/migrate_prices_main.py` — 4.4 и 4.5 как квартальные ✅
- `migration/migrate_prices_subtypes.py` — 4.4.1–4.5.4 по типам жилья ✅

### Блок 6 — Увязка навигации ⏳ ТЕКУЩАЯ ЗАДАЧА

**Проблема:** `category.html` показывает все индикаторы как отдельные карточки → `chart.html?code=X`. Комбо-страницы изолированы.

**Решение:** `COMBO_OVERRIDES` — JS-константа с тремя режимами для каждой записи:
- `parentCode` — заменить карточку этого индикатора ссылкой на combo URL
- `hideCodes` — скрыть эти индикаторы из списка
- `parentCode: null` — добавить новую карточку (комбо без родителя)

**Полная карта замен:**

| Категория | parentCode | URL | hideCodes |
|-----------|-----------|-----|-----------|
| `supply_volume` | `2.1` | combo-chart.html | `['2.2']` |
| `supply_volume` | null | share-chart.html | `[]` |
| `concentration` | `3.17` | ihh-chart.html | `['3.18']` |
| `prices` | `4.4` | prices-chart.html | `['4.5']` |
| `mortgage_primary` | `6.7` | mortgage-count.html | `['6.13']` |
| `mortgage_primary` | `6.8` | mortgage-volume.html | `['6.14']` |
| `mortgage_primary` | `6.9` | mortgage-rate.html | `['6.15']` |
| `mortgage_primary` | `6.10` | mortgage-term.html | `['6.16']` |
| `mortgage_primary` | `6.11` | mortgage-size.html | `['6.17']` |
| `mortgage_primary` | `6.12` | mortgage-payment.html | `['6.18']` |
| `mortgage_subsidy` | `6.36` | subsidy-count.html | `['6.37','6.38','6.39']` |
| `mortgage_subsidy` | `6.46` | subsidy-volume.html | `['6.47','6.48','6.49']` |
| `mortgage_subsidy` | `6.50` | subsidy-ddu-count.html | `['6.51','6.52','6.53']` |
| `mortgage_subsidy` | `6.56` | subsidy-ddu-volume.html | `['6.57','6.58','6.59']` |
| `mortgage_igs` | `6.70` | igs-count.html | `['6.76','6.82']` |
| `mortgage_igs` | `6.71` | igs-volume.html | `['6.77','6.83']` |
| `mortgage_igs` | `6.72` | igs-rate.html | `['6.78','6.84']` |
| `mortgage_igs` | `6.73` | igs-term.html | `['6.79','6.85']` |
| `mortgage_igs` | `6.74` | igs-size.html | `['6.80','6.86']` |
| `mortgage_igs` | `6.75` | igs-payment.html | `['6.81','6.87']` |

---

## Полный список файлов проекта

### Backend
| Файл | Что делает |
|------|-----------|
| `backend/app/main.py` | FastAPI app, CORS middleware, роутеры |
| `backend/app/config.py` | Pydantic Settings, database_url |
| `backend/app/database.py` | SQLAlchemy engine, Session, get_db |
| `backend/app/models.py` | ORM: Source, Category, Indicator, DataPoint, UpdateJob |
| `backend/app/schemas.py` | Pydantic v2 schemas (CategoryOut, IndicatorBrief/Full, DataPointOut, TimeSeriesOut…) |
| `backend/app/routers/categories.py` | GET /api/categories |
| `backend/app/routers/indicators.py` | /api/categories/{code}/indicators, /api/indicators/{code}/data, /api/multi/data, /api/multi/data.xlsx, /api/search |
| `backend/app/routers/meta.py` | GET /api/meta/last-update |
| `backend/app/services/data_service.py` | get_indicator_list_for_category, get_time_series (с YoY/MoM), search_indicators |
| `backend/app/services/export_service.py` | export_indicator_xlsx, export_multi_xlsx (2 листа: Данные + Годовые) |
| `backend/Dockerfile` | python:3.11-slim, uvicorn port 8000 |
| `backend/requirements.txt` | fastapi, uvicorn, sqlalchemy, psycopg2-binary, pydantic, openpyxl |

### Frontend
| Файл | Что делает |
|------|-----------|
| `frontend/index.html` | Главная: hero, сетка категорий, таблица обновлений, поиск |
| `frontend/category.html` | Список показателей раздела со sparkline и YoY |
| `frontend/chart.html` | Страница индикатора: ECharts, KPI, toolbar, таблица, "Ещё по теме" |
| `frontend/css/variables.css` | CSS-переменные: цвета, шрифты (IBM Plex Sans/Mono, Playfair Display), тени |
| `frontend/css/main.css` | Общие стили: header, footer, hero, category-grid, delta-badges, skeleton |
| `frontend/css/chart.css` | Стили chart/category: sidebar, breadcrumb, KPI-row, toolbar, data-table, related |
| `frontend/js/api.js` | API-клиент: fetch-обёртки для всех эндпоинтов |
| `frontend/js/utils.js` | fmtNum, fmtValue, fmtDate, deltaHtml (п.п. поддержка), cleanName, rangeStart |
| `frontend/js/sparkline.js` | SVG sparkline без зависимостей |
| `frontend/js/chart-page.js` | Полная логика chart.html: ECharts init, KPI, table, related, search dropdown |
| `frontend/combo-chart.html` | МЖС+ИЖС стековая гистограмма |
| `frontend/share-chart.html` | Структура ввода % (100%-стек) |
| `frontend/ihh-chart.html` | ИХХ средний+медианный |
| `frontend/prices-chart.html` | Цены Росстат с двухуровневыми вкладками |
| `frontend/mortgage-count.html` … `mortgage-payment.html` | 6 страниц ипотеки первич/вторич |
| `frontend/subsidy-count.html` … `subsidy-ddu-volume.html` | 4 страницы господдержки |
| `frontend/igs-count.html` … `igs-payment.html` | 6 страниц ипотеки ИЖС |

### Миграция и парсеры
| Файл | Что делает |
|------|-----------|
| `migration/001_init.sql` | DDL + начальные данные sources/categories |
| `migration/excel_to_db.py` | Паттерны A/B-simple/B-cum/C, upsert, refresh view |
| `migration/fetch_fedstat.py` | POST dataGrid.do для 6 индикаторов |
| `migration/migrate_prices_main.py` | 4.4 и 4.5 как квартальные |
| `migration/migrate_prices_subtypes.py` | 4.4.1–4.5.4 по типам жилья |
| `parsers/base.py` | BaseParser: retry, upsert, job log, refresh view |
| `parsers/cbr.py` | Скачивает Excel с сайта ЦБ, парсит ипотечную статистику |
| `parsers/domrf.py` | Публичный API наш.дом.рф/api/opendata |
| `parsers/rosstat.py` | ЕМИСС API fedstat.ru |
| `parsers/scheduler.py` | APScheduler для локального запуска |

---

## Оставшиеся задачи (приоритет ↓)

| # | Задача | Блок | Статус |
|---|--------|------|--------|
| 1 | **Увязка комбо-страниц с category.html** | 6 | ⏳ Текущая |
| 2 | Расчёт 2.10 обеспеченность жильём | 3 | ⏳ |
| 3 | Расчёт 5.9 темп продаж | 3 | ⏳ |
| 4 | Расчёт 5.10 КДЖ доступность | 3 | ⏳ |
| 5 | Минимальные значения осей Y (2.9 Жилфонд) | — | ⏳ |
| 6 | 1.1 Население — найти альтернативный источник | 2 | ❌ |
| 7 | 2.13.ext данные после 2015 | 2 | ❌ |
| 8 | Парсеры domclick.py и rosreestr.py | 4 | ⏳ |
| 9 | Деплой на VPS (Docker + SSL) | 7 | ⏳ |

---

## Ключевые технические решения

| Решение | Причина |
|---------|---------|
| ECharts вместо Highcharts | Бесплатная лицензия Apache 2.0 |
| Vanilla HTML/JS без Node.js | Нет сборщика — деплой = копирование файлов |
| Backend синхронный (нет async) | Достаточно для начального трафика |
| Только абсолютные значения в data_points | YoY/MoM/YTD считает materialized view |
| Комбо-страницы как отдельные HTML | Не ломает API, не требует schema-изменений |
| fedstat POST dataGrid.do | Официальный API нестабильный и медленный |
| periodicity = 'quarterly' для 1.2, 1.3 | Данные выходят поквартально |
| COMBO_OVERRIDES в JS | Нет изменений в БД/API для навигационных правил |
