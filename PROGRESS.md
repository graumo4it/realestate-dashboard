# PROGRESS.md — Трекер разработки
## Дашборд «Статистика рынка жилой недвижимости России»

> Последнее обновление: 5 мая 2026
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

# Python окружение (venv)
source venv/bin/activate
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
| `1.1` | Население | 36 | 1990–2025, захардкожено + парсер fedstat/31557 |

### Блок 3 — Расчётные индикаторы ⏳

| Код | Формула | Статус |
|-----|---------|--------|
| `2.10` Обеспеченность жильём на конец года | жилфонд[N] / население[N+1] | ✅ |
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
| `subsidy-count.html` | 6.36, 6.38, 6.40, 6.42, 6.44 | bar stacked |
| `subsidy-volume.html` | 6.37, 6.39, 6.41, 6.43, 6.45 | bar stacked |
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

### Блок 6 — Увязка навигации ✅

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
| `apartments` | `apartments_count_total` | apartments-count.html | `['apartments_count_1k'..'4k']` |
| `apartments` | `apartments_area_total` | apartments-area.html | `['apartments_area_1k'..'4k']` |
| `apartments` | null | apartments-share.html | `['apartments_share_1k'..'4k']` |
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

## Блок правок v1.2 — май 2026

### Раздел «Ипотека (льготные программы)» ✅

| Задача | Статус | Детали |
|--------|--------|--------|
| Переименование категории `mortgage_subsidy` | ✅ | «Господдержка» → «Ипотека (льготные программы)» в БД и хлебных крошках |
| Обновление данных по всем программам господдержки | ✅ | Источник: лист `01_02_01` файла `Статистические_ряды__РФ_-3.xlsx`, янв 2018 – мар 2026 |
| Создание новых индикаторов 6.44 / 6.45 | ✅ | «Ипотека в отдельных регионах»: количество и объём кредитов |
| Замена плашки «Льготная» → «Отдельные регионы» | ✅ | Льготная ипотека завершена в дек 2024; в KPI-плашках теперь активные программы |
| Обновление `subsidy-count.html` | ✅ | 5 серий: Семейная / Дальневосточная / IT / Отдельные регионы / Льготная (история) |
| Обновление `subsidy-volume.html` | ✅ | Аналогично, 5 серий |

**Маппинг кодов БД (актуальный):**

| Код | Индикатор |
|-----|-----------|
| `6.36` | Семейная ипотека — количество кредитов |
| `6.37` | Семейная ипотека — объём кредитов |
| `6.38` | Льготная ипотека — количество (завершена дек 2024) |
| `6.39` | Льготная ипотека — объём (завершена дек 2024) |
| `6.40` | Дальневосточная и арктическая — количество |
| `6.41` | Дальневосточная и арктическая — объём |
| `6.42` | IT-ипотека — количество |
| `6.43` | IT-ипотека — объём |
| `6.44` | Ипотека в отдельных регионах — количество (**новый**) |
| `6.45` | Ипотека в отдельных регионах — объём (**новый**) |

**Скрипт миграции:** `migration/migrate_subsidy_update.py`

---

### Раздел «Уровень концентрации» ✅

| Задача | Статус | Детали |
|--------|--------|--------|
| Скрытие 3.19 со страницы раздела | ✅ | `is_public = false` |
| Загрузка данных 3.18 и 3.19 | ✅ | Источник: лист `01_01_00`, янв 2020 – апр 2026, 76 точек |
| Исправление `get_indicator_by_code` в `data_service.py` | ✅ | Убран фильтр `is_public=True` — скрытые индикаторы доступны для комбо-страниц |
| Перенос показателя 3.6 в раздел «Уровень концентрации» | ✅ | SQL: `UPDATE indicators SET category_id = ... WHERE code = '3.6'` |

**Скрипт миграции:** `migration/migrate_ihh_update.py`

---

### Раздел «Строящееся жильё» ✅

| Задача | Статус | Детали |
|--------|--------|--------|
| Загрузка данных 3.1, 3.2, 3.3, 3.4 | ✅ | Источник: лист `01_01_00`, янв 2020 – апр 2026, 76 точек каждый |

**Скрипт миграции:** `migration/migrate_under_construction.py`

---

### Раздел «Квартирография» — покупные данные ДОМ.РФ ✅

Данные из трёх закрытых файлов ДОМ.РФ (не в открытом доступе).

**Структура хранения файлов** (в `.gitignore`):
```
migration/domrf_data/
├── matrix_projects/   ← Матрица проектов (*.xlsb / *.xlsx, по дате)
├── apartments/        ← Квартирография (*.xlsb / *.xlsx, по дате)
└── sales_matrix/      ← Матрица продаж (один накопительный *.xlsx)
```

**Созданные индикаторы:**

| Код | Название | Источник | Периодов |
|-----|----------|----------|----------|
| `3.6` | Доля топ-5 застройщиков | Матрица проектов | 44 |
| `apartments_count_1k/2k/3k/4k` | Кол-во квартир по комнатности | Квартирография | 53 |
| `apartments_count_total` | Кол-во квартир всего | Квартирография | 53 |
| `apartments_area_1k/2k/3k/4k` | Средняя площадь по комнатности | Квартирография | 53 |
| `apartments_area_total` | Средняя площадь всего | Квартирография | 53 |
| `apartments_share_1k/2k/3k/4k` | Структура по комнатности, % | Квартирография | 53 |
| `apt_budget` | Средний бюджет сделки с квартирой | Матрица продаж | 63 |
| `apt_area` | Средняя площадь квартиры в сделке | Матрица продаж | 63 |
| `mm_budget` | Средний бюджет машиноместа, млн руб. | Матрица продаж | 63 |

**Пересчитаны из Матрицы продаж (данные 2021+):**

| Код | Примечание |
|-----|-----------|
| `4.1` | Средняя цена 1 кв. м квартир (данные за 2020 сохранены) |
| `5.8` | Количество сделок с квартирами (данные за 2020 сохранены) |
| `5.20` | Количество сделок с машиноместами (перенесено из mm_count) |
| `5.21` | Средняя площадь машиноместа (перенесено из mm_area) |
| `5.22` | Темп продаж машиномест — добавлен март 2026 |
| `5.9` | Темп продаж квартир — добавлен март 2026 |

**Особенности обработки данных:**
- Файлы до 2023: нет столбца статуса → статус берётся из Матрицы проектов за тот же месяц (ключ: `Корпус`, нормализация к строке целого числа)
- Файлы дек.2021, янв.2022: формат без площади (`1-комнатные`/`2-комнатные`) → area = NULL
- Файлы фев–май 2022: формат `.xlsx` → поддержан отдельный ридер
- Некорректные периоды (сен.2023, дек.2023, янв.2024): интерполяция между граничными точками

**Скрипты миграции:**
- `migration/002_domrf_private_indicators.sql` — создание индикаторов (1 раз)
- `migration/migrate_matrix_projects.py` — показатель 3.6
- `migration/migrate_apartments.py` — квартирография (14 индикаторов)
- `migration/migrate_sales_matrix.py` — матрица продаж (8 показателей, окно: пред. год + текущий)
- `migration/recalc_mm_budget.py` — полный пересчёт mm_budget за всю историю

**Комбо-страницы квартирографии:**
- `frontend/apartments-count.html` — количество квартир по комнатности (stacked bar)
- `frontend/apartments-area.html` — средняя площадь по комнатности (line)
- `frontend/apartments-share.html` — структура по комнатности, % (100% bar)

**SQL-правки:**
- `3.13`, `3.14`, `3.15`, `3.16` — скрыты (`is_public = false`), заменены новыми индикаторами
- `mm_count`, `mm_area` — скрыты после переноса данных в `5.20`/`5.21`
- `mm_budget` — перенесён из раздела `prices` в `demand`, единица изменена на `млн руб.`

**Ежемесячное обновление:**
```bash
# Добавить новый файл в matrix_projects/ и apartments/ (старые не удалять)
# Заменить файл в sales_matrix/
python migration/migrate_matrix_projects.py
python migration/migrate_apartments.py
python migration/migrate_sales_matrix.py
```

---

## Полный список файлов проекта

### Backend
| Файл | Что делает |
|------|-----------|
| `backend/app/main.py` | FastAPI app, CORS middleware, роутеры |
| `backend/app/config.py` | Pydantic Settings, database_url |
| `backend/app/database.py` | SQLAlchemy engine, Session, get_db |
| `backend/app/models.py` | ORM: Source, Category, Indicator, DataPoint, UpdateJob |
| `backend/app/schemas.py` | Pydantic v2 schemas |
| `backend/app/routers/categories.py` | GET /api/categories |
| `backend/app/routers/indicators.py` | /api/categories/{code}/indicators, /api/indicators/{code}/data, /api/multi/data, /api/multi/data.xlsx, /api/search |
| `backend/app/routers/meta.py` | GET /api/meta/last-update |
| `backend/app/services/data_service.py` | get_indicator_list_for_category, get_indicator_by_code (без фильтра is_public), get_time_series, search_indicators |
| `backend/app/services/export_service.py` | export_indicator_xlsx, export_multi_xlsx (2 листа: Данные + Годовые) |
| `backend/Dockerfile` | python:3.11-slim, uvicorn port 8000 |
| `backend/requirements.txt` | fastapi, uvicorn, sqlalchemy, psycopg2-binary, pydantic, openpyxl |

### Frontend
| Файл | Что делает |
|------|-----------|
| `frontend/index.html` | Главная: hero, сетка категорий, таблица обновлений, поиск |
| `frontend/category.html` | Список показателей раздела со sparkline и YoY |
| `frontend/chart.html` | Страница индикатора: ECharts, KPI, toolbar, таблица, "Ещё по теме" |
| `frontend/css/variables.css` | CSS-переменные: цвета, шрифты, тени |
| `frontend/css/main.css` | Общие стили |
| `frontend/css/chart.css` | Стили chart/category |
| `frontend/js/api.js` | API-клиент |
| `frontend/js/utils.js` | fmtNum, fmtValue, fmtDate, deltaHtml, cleanName, rangeStart |
| `frontend/js/sparkline.js` | SVG sparkline без зависимостей |
| `frontend/js/chart-page.js` | Полная логика chart.html |
| `frontend/combo-chart.html` | МЖС+ИЖС стековая гистограмма |
| `frontend/share-chart.html` | Структура ввода % (100%-стек) |
| `frontend/ihh-chart.html` | ИХХ средний+медианный |
| `frontend/prices-chart.html` | Цены Росстат с двухуровневыми вкладками |
| `frontend/mortgage-count.html` … `mortgage-payment.html` | 6 страниц ипотеки первич/вторич |
| `frontend/subsidy-count.html` | Количество кредитов по программам: 5 серий |
| `frontend/subsidy-volume.html` | Объём кредитов по программам: 5 серий |
| `frontend/subsidy-ddu-count.html`, `subsidy-ddu-volume.html` | Господдержка ДДУ |
| `frontend/igs-count.html` … `igs-payment.html` | 6 страниц ипотеки ИЖС |
| `frontend/per-capita-chart.html` | Ввод жилья на душу: Всего/МЖС/ИЖС — line |
| `frontend/apartments-count.html` | Квартирография: количество квартир по комнатности (stacked bar) |
| `frontend/apartments-area.html` | Квартирография: средняя площадь по комнатности (line) |
| `frontend/apartments-share.html` | Квартирография: структура по комнатности, % (100% bar) |

### Миграция и парсеры
| Файл | Что делает |
|------|-----------|
| `migration/001_init.sql` | DDL + начальные данные sources/categories |
| `migration/002_domrf_private_indicators.sql` | Создание индикаторов квартирографии и матрицы продаж |
| `migration/excel_to_db.py` | Паттерны A/B-simple/B-cum/C, upsert, refresh view |
| `migration/fetch_fedstat.py` | POST dataGrid.do для 6 индикаторов |
| `migration/migrate_prices_main.py` | 4.4 и 4.5 как квартальные |
| `migration/migrate_prices_subtypes.py` | 4.4.1–4.5.4 по типам жилья |
| `migration/migrate_subsidy_update.py` | Обновление данных льготных программ + создание 6.44/6.45 |
| `migration/migrate_ihh_update.py` | Данные ИХХ 3.18/3.19 из 01_01_00, скрытие 3.19 |
| `migration/migrate_under_construction.py` | Данные строящегося жилья 3.1–3.4 из 01_01_00 |
| `migration/migrate_population_1990_2010.py` | Численность населения 1.1 за 1990–2025 (захардкожено) |
| `migration/calc_housing_provision.py` | Расчёт 2.10 обеспеченность жильём на конец года |
| `migration/migrate_matrix_projects.py` | Доля топ-5 застройщиков (3.6) из Матрицы проектов |
| `migration/migrate_apartments.py` | Квартирография (14 индикаторов) из файлов Квартирографии |
| `migration/migrate_sales_matrix.py` | 8 показателей из Матрицы продаж (окно: пред.+тек. год) |
| `migration/recalc_mm_budget.py` | Полный пересчёт mm_budget за всю историю |
| `parsers/fetch_fedstat_31557.py` | Парсер населения fedstat/31557 (только локально) |
| `parsers/base.py` | BaseParser: retry, upsert, job log, refresh view |
| `parsers/cbr.py` | Скачивает Excel с сайта ЦБ, парсит ипотечную статистику |
| `parsers/domrf.py` | Публичный API наш.дом.рф/api/opendata |
| `parsers/rosstat.py` | ЕМИСС API fedstat.ru |
| `parsers/scheduler.py` | APScheduler для локального запуска |

---

## Оставшиеся задачи (приоритет ↓)

| # | Задача | Блок | Статус |
|---|--------|------|--------|
| 1 | Расчёт 5.10 КДЖ доступность | 3 | ⏳ |
| 2 | Расчёт 5.11 доступность по ипотеке | 3 | ⏳ |
| 3 | Расчёт 5.12–5.15 потребность в жилье | 3 | ⏳ |
| 4 | 2.13.ext данные после 2015 | 2 | ❌ недоступно в fedstat |
| 5 | Парсеры domclick.py и rosreestr.py | 4 | ⏳ |
| 6 | Деплой на VPS (Docker + SSL) | 7 | ⏳ |

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
| `get_indicator_by_code` без фильтра `is_public` | Скрытые индикаторы доступны для комбо-страниц через `/api/multi/data`, но скрыты в навигации/поиске |
| Льготная ипотека 6.38/6.39 — `is_public=true`, нули→NULL | Исторические данные сохранены, пустые периоды не отображаются |
| Квартирография: статус из Матрицы проектов | Старые файлы без столбца статуса — джойн по ключу `Корпус` |
| Квартирография: интерполяция плохих периодов | BAD_PERIODS в migrate_apartments.py: сен.2023, дек.2023, янв.2024 |
| mm_budget в млн руб. | Удобочитаемость: значения 1–3 вместо 1 000 000–3 000 000 |
| migrate_sales_matrix.py: окно пред.+тек. год | Источник пересматривает данные за предыдущий год ежемесячно |

---

## АРХИВ — Выполненные промпты

### Промпт 1.1 — .gitignore, .env.example, README ✅
### Промпт 1.2 — CI workflow (ruff линтинг) ✅
### Промпт 1.3 — Deploy workflow (SSH на VPS) ✅
### Промпт 2.1 — SQL-схема БД ✅ → `migration/001_init.sql`
### Промпт 2.2 — Миграция Excel → БД ✅ → `migration/excel_to_db.py`
### Промпт 3.1 — FastAPI основа ✅ → `backend/app/main.py`, `config.py`, `database.py`, `models.py`
### Промпт 3.2 — Pydantic-схемы ✅ → `backend/app/schemas.py`
### Промпт 3.3 — Роутеры и сервисы ✅ → `/api/categories`, `/api/indicators/*/data`, `/api/multi/data`, `/api/multi/data.xlsx`
### Промпт 5.1 — Общие файлы фронтенда ✅ → `css/variables.css`, `css/main.css`, `js/api.js`, `js/utils.js`
### Промпт 5.2 — Главная страница ✅ → `frontend/index.html`
### Промпт 5.3 — Страница раздела + sparkline ✅ → `frontend/category.html`, `js/sparkline.js`
### Промпт 5.4 — Страница показателя с ECharts ✅ → `frontend/chart.html`, `css/chart.css`, `js/chart-page.js`
### Промпт 4.1 — BaseParser ✅ → `parsers/base.py`
### Промпт 4.2 — Парсер ЦБ РФ ✅ → `parsers/cbr.py`
### Промпт 4.3 — Парсер ДОМ.РФ ✅ → `parsers/domrf.py`
### Промпт 4.4 — Парсер Росстат ✅ → `parsers/rosstat.py`
### Промпт 4.5 — GitHub Actions для парсеров ✅ → `.github/workflows/parse-cbr.yml`, `parse-domrf.yml`, `parse-rosstat.yml`
### Промпт 6.1 — docker-compose.prod.yml + nginx ✅ → `docker-compose.prod.yml`, `nginx/nginx.conf`

### Промпты блока правок v1.1 (выполнены итеративно):
- MoM в backend/frontend, KPI-плашки, dataZoom, cleanName, п.п. для ставок ✅
- Комбо-страницы: combo-chart, share-chart, ihh-chart, prices-chart ✅
- Комбо-страницы: mortgage-count/volume/rate/term/size/payment ✅
- Комбо-страницы: subsidy-count/volume/ddu-count/ddu-volume ✅
- Комбо-страницы: igs-count/volume/rate/term/size/payment ✅
- fedstat миграция: 1.2, 1.3, 2.9, 2.11, 2.12, 2.13.ext ✅
- Миграция цен Росстат: 4.4, 4.5 (quarterly) + 4.4.1–4.5.4 (subtypes) ✅
- export_multi_xlsx() — универсальный экспорт с двумя листами ✅
- /api/multi/data и /api/multi/data.xlsx эндпоинты ✅

### Блок правок v1.2 — май 2026:
- Раздел «Ипотека (льготные программы)»: переименование, новые индикаторы 6.44/6.45, обновление subsidy-count/volume.html ✅
- Раздел «Уровень концентрации»: данные 3.18/3.19, скрытие 3.19, fix data_service.py, перенос 3.6 в раздел ✅
- Раздел «Строящееся жильё»: данные 3.1–3.4 из 01_01_00 ✅
- 1.1 Население: данные 1990–2025 захардкожены + парсер fedstat/31557 ✅
- 2.10 Обеспеченность жильём на конец года: расчёт жилфонд[N]/население[N+1] ✅
- Увязка навигации COMBO_OVERRIDES: все 20 комбо-страниц увязаны с category.html ✅
- Новая комбо-страница per-capita-chart.html: ввод жилья на душу (2.6/2.7/2.8) ✅
- Раздел supply_per_capita удалён, показатели 2.6/2.7/2.8 перенесены в supply_volume ✅
- share-chart.html: добавлен режим «Изм. м/м, п.п.», колонка м/м в таблице ✅
- Спарклайны: поддержка annual (10 лет), fallback для устаревших данных ✅

### Блок правок v1.3 — 5 мая 2026:
- Покупные данные ДОМ.РФ: инфраструктура хранения и миграции ✅
- migrate_matrix_projects.py: показатель 3.6, 44 периода с июн.2022 ✅
- migrate_apartments.py: 14 индикаторов квартирографии, 53 периода с дек.2021 ✅
  - Поддержка xlsb + xlsx, старых форматов столбцов, нормализация ключа Корпус
  - Интерполяция некорректных периодов (сен.2023, дек.2023, янв.2024)
- migrate_sales_matrix.py: 8 показателей из Матрицы продаж (2025 – март 2026) ✅
- recalc_mm_budget.py: mm_budget за полную историю (янв.2021 – март 2026, 63 точки) ✅
- SQL: 002_domrf_private_indicators.sql — создание 14+6 индикаторов ✅
- Комбо-страницы квартирографии: apartments-count/area/share.html ✅
- COMBO_OVERRIDES: добавлен раздел apartments (3 записи) ✅
- Старые показатели 3.13–3.16 скрыты (is_public = false) ✅
- mm_count, mm_area скрыты; данные перенесены в 5.20, 5.21 ✅
- mm_budget: перенесён в раздел demand, единица млн руб. ✅
- 5.9, 5.22: добавлен март 2026 (42832.67 и 4826.33 сделок) ✅
