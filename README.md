# Статистика рынка жилой недвижимости России

Публичный информационный сайт с интерактивными дашбордами по рынку жилой недвижимости России.
Более 110 показателей: ипотека, цены, ввод жилья, спрос, застройщики.
Данные из Банка России, Росстата, ДОМ.РФ, Домклик, Росреестра.

---

## Структура репозитория

```
realestate-dashboard/
├── .github/
│   └── workflows/
│       ├── ci.yml               ← линтинг при каждом push
│       ├── deploy.yml           ← деплой при merge в main
│       ├── parse-cbr.yml        ← парсер ЦБ РФ (по пн)
│       ├── parse-domrf.yml      ← парсер ДОМ.РФ (ежедневно)
│       └── parse-rosstat.yml    ← парсер Росстат (по пн)
├── backend/
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── models.py
│       ├── schemas.py
│       ├── routers/
│       │   ├── categories.py
│       │   ├── indicators.py
│       │   └── meta.py
│       └── services/
│           ├── data_service.py
│           └── export_service.py
├── parsers/
│   ├── base.py
│   ├── cbr.py
│   ├── domrf.py
│   └── rosstat.py
├── migration/
│   ├── 001_init.sql             ← схема БД
│   ├── excel_to_db.py           ← импорт из Excel
│   └── data/                   ← сюда кладём Excel (в .gitignore)
├── frontend/
│   ├── index.html
│   ├── category.html
│   ├── chart.html
│   ├── css/
│   │   ├── variables.css
│   │   ├── main.css
│   │   └── chart.css
│   └── js/
│       ├── api.js
│       ├── utils.js
│       ├── sparkline.js
│       └── chart-page.js
├── nginx/
│   └── nginx.conf
├── docker-compose.prod.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## Быстрый старт (локально, без Docker)

### 1. Установить зависимости

- [Python 3.11](https://python.org)
- [PostgreSQL 16](https://postgresql.org) — установить локально

### 2. Склонировать и настроить

```bash
git clone https://github.com/<username>/realestate-dashboard.git
cd realestate-dashboard

cp .env.example .env
# Отредактировать .env — вставить DB_USER и DB_PASSWORD
```

### 3. Создать схему БД

```bash
# Создать базу данных (один раз)
psql -U postgres -c "CREATE DATABASE realestate;"

# Применить схему
psql -U postgres -d realestate -f migration/001_init.sql
```

### 4. Импортировать данные из Excel

```bash
cd migration
pip install -r requirements.txt
cp /path/to/your.xlsx data/
python excel_to_db.py data/your.xlsx
```

### 5. Запустить backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Документация API: http://localhost:8000/docs
```

### 6. Запустить frontend

```bash
# Вариант 1: просто открыть index.html в браузере
# Вариант 2: HTTP-сервер (нужен для ES-модулей в Safari)
cd frontend
python -m http.server 8080
# открыть http://localhost:8080
```

---

## Продакшн-деплой (Docker Compose)

```bash
# На VPS с Ubuntu 22.04 + Docker

git clone https://github.com/<username>/realestate-dashboard.git
cd realestate-dashboard

# Создать .env.prod с продакшн-значениями
cp .env.example .env.prod
nano .env.prod  # заполнить DB_USER, DB_PASSWORD и т.д.

# Запустить
docker compose -f docker-compose.prod.yml up -d

# Применить схему БД (один раз)
docker compose -f docker-compose.prod.yml exec db \
  psql -U $DB_USER -d $DB_NAME -f /migration/001_init.sql

# Проверить
curl http://localhost/api/categories
```

---

## Переменные окружения

| Переменная | Описание | Пример |
|---|---|---|
| `DB_HOST` | Хост PostgreSQL | `localhost` / `db` (Docker) |
| `DB_PORT` | Порт | `5432` |
| `DB_NAME` | Имя базы | `realestate` |
| `DB_USER` | Пользователь БД | `postgres` |
| `DB_PASSWORD` | Пароль БД | *(секрет)* |
| `CORS_ORIGINS` | Разрешённые origins для CORS | `["http://localhost:8080"]` |
| `SITE_NAME` | Название сайта | `Статистика рынка недвижимости` |
| `TELEGRAM_BOT_TOKEN` | Токен бота для уведомлений об ошибках | *(опционально)* |
| `TELEGRAM_CHAT_ID` | ID чата Telegram | *(опционально)* |

---

## API эндпоинты

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/categories` | Список тематических разделов |
| GET | `/api/categories/{code}/indicators` | Показатели раздела |
| GET | `/api/indicators/{code}` | Метаданные показателя |
| GET | `/api/indicators/{code}/data` | Временной ряд |
| GET | `/api/indicators/{code}/data.xlsx` | Скачать данные в Excel |
| GET | `/api/search?q=` | Поиск по показателям |
| GET | `/api/meta/last-update` | Дата последнего обновления |

Интерактивная документация: `http://localhost:8000/docs`

---

## Ветки и рабочий процесс

```
main          ← продакшн, защищённая (только через PR)
  └── dev     ← основная ветка разработки
        ├── feature/название-задачи
        └── fix/название-исправления
```

Commit-сообщения: `feat:`, `fix:`, `chore:`, `docs:` (Conventional Commits)

---

## Источники данных

| Источник | Парсер | Расписание |
|---|---|---|
| Банк России | `parsers/cbr.py` | По понедельникам 06:00 UTC |
| ДОМ.РФ | `parsers/domrf.py` | Ежедневно 04:00 UTC |
| Росстат / ЕМИСС | `parsers/rosstat.py` | По понедельникам 06:30 UTC |

---

## Лицензия

Код: MIT. Данные: открытые источники (ЦБ РФ, Росстат, ДОМ.РФ, Росреестр).
