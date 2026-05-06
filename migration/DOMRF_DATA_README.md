# Миграция данных из покупных файлов ДОМ.РФ

## Структура папок

```
migration/
├── domrf_data/                    ← в .gitignore (покупные данные)
│   ├── matrix_projects/           ← Матрица проектов (по дате)
│   │   ├── Матрица_проектов_15_04_2026.xlsb
│   │   ├── Матрица_проектов_15_05_2026.xlsb
│   │   └── ...
│   ├── apartments/                ← Квартирография (по дате)
│   │   ├── Квартирография_15_04_2026.xlsb
│   │   ├── Квартирография_15_05_2026.xlsb
│   │   └── ...
│   └── sales_matrix/              ← Матрица продаж (один накопительный файл)
│       └── Матрица_продаж.xlsx    ← каждый месяц заменяется новой версией
│
├── 002_domrf_private_indicators.sql  ← SQL: создание новых индикаторов (1 раз)
├── migrate_matrix_projects.py        ← парсер Матрицы проектов → 3.6
├── migrate_apartments.py             ← парсер Квартирографии → apartments_*
└── migrate_sales_matrix.py           ← парсер Матрицы продаж → 4.1, 5.8, apt_*, mm_*
```

## Первоначальная настройка (один раз)

```bash
# 1. Создать папки для данных
mkdir -p migration/domrf_data/matrix_projects
mkdir -p migration/domrf_data/apartments
mkdir -p migration/domrf_data/sales_matrix

# 2. Добавить папку в .gitignore (если ещё нет)
echo "migration/domrf_data/" >> .gitignore

# 3. Создать новые индикаторы в БД
psql -U $DB_USER -d $DB_NAME -f migration/002_domrf_private_indicators.sql

# 4. Установить зависимость
pip install pyxlsb
```

## Первая загрузка данных

```bash
# Положить файлы за все доступные периоды в папки:
#   migration/domrf_data/matrix_projects/Матрица_проектов_15_12_2021.xlsb
#   migration/domrf_data/matrix_projects/Матрица_проектов_15_01_2022.xlsb
#   ... (все файлы с декабря 2021)
#   migration/domrf_data/apartments/Квартирография_15_12_2021.xlsb
#   ...
#   migration/domrf_data/sales_matrix/Матрица_продаж.xlsx  (полный файл)

# Запустить скрипты
cd /opt/realestate-dashboard  # или корень репозитория
python migration/migrate_matrix_projects.py
python migration/migrate_apartments.py
python migration/migrate_sales_matrix.py
```

## Ежемесячное обновление

Каждый месяц (после получения новых файлов от ДОМ.РФ):

```bash
# 1. Матрица проектов — добавить новый файл в папку (старые не удалять)
cp ~/downloads/Матрица_проектов_15_05_2026.xlsb migration/domrf_data/matrix_projects/
python migration/migrate_matrix_projects.py
# Скрипт пересчитает ВСЕ файлы заново (DELETE + INSERT)

# 2. Квартирография — добавить новый файл (старые не удалять)
cp ~/downloads/Квартирография_15_05_2026.xlsb migration/domrf_data/apartments/
python migration/migrate_apartments.py

# 3. Матрица продаж — ЗАМЕНИТЬ файл (старый удалить)
cp ~/downloads/Матрица_продаж.xlsx migration/domrf_data/sales_matrix/
python migration/migrate_sales_matrix.py
# Скрипт пересчитает все периоды с 2021-01-01
```

## Соглашение по именованию файлов

Скрипты автоматически извлекают дату периода из имени файла:

```
Матрица_проектов_15_04_2026.xlsb  →  period_date = 2026-04-01
Квартирография_15_12_2021.xlsb    →  period_date = 2021-12-01
```

Паттерн: `*_DD_MM_YYYY.xlsb` — цифры в формате день_месяц_год.

## Индикаторы и расчёты

### Матрица проектов → показатель 3.6

| Фильтр | Числитель | Знаменатель |
|--------|-----------|-------------|
| Статус корпуса = «Строится» | Жилая площадь топ-5 групп компаний | Жилая площадь всех строящихся |

Топ-5 считается по объёму (кв. м), а не по количеству корпусов.

### Квартирография → apartments_count/area/share

| Код | Что считаем |
|-----|-------------|
| `apartments_count_{1-4}k` | Количество квартир по типу, шт. |
| `apartments_count_total` | Итого квартир, шт. |
| `apartments_area_{1-4}k` | Взвешенная средняя площадь по типу, кв. м |
| `apartments_area_total` | Взвешенная средняя площадь (все типы), кв. м |
| `apartments_share_{1-4}k` | Доля типа в общем количестве, % |

Дочерние индикаторы (1k–4k) имеют `is_public=false` — они используются
только внутри комбо-страниц квартирографии.

### Матрица продаж → несколько показателей

| Код | Формула |
|-----|---------|
| `5.8` | sum(Продано квартир, шт.) |
| `4.1` | sum(Продано квартир, руб.) / sum(Продано квартир, м2) |
| `apt_budget` | sum(Продано квартир, руб.) / sum(Продано квартир, шт.) |
| `apt_area` | sum(Продано квартир, м2) / sum(Продано квартир, шт.) |
| `mm_count` | sum(Продано машиномест, шт.) |
| `mm_price` | sum(Продано машиномест, руб.) / sum(Продано машиномест, м2) |
| `mm_budget` | sum(Продано машиномест, руб.) / sum(Продано машиномест, шт.) |
| `mm_area` | sum(Продано машиномест, м2) / sum(Продано машиномест, шт.) |

Данные за 2020 год у `5.8` и `4.1` сохраняются из предыдущей загрузки.
При каждом запуске данные с 2021-01-01 пересчитываются полностью.
