# PROGRESS.md — Трекер разработки

## Статус этапов

| # | Задача | Статус | Файлы |
|---|--------|--------|-------|
| 1 | Структура репозитория, .gitignore, README | ✅ Готово | `.gitignore`, `README.md`, `PROGRESS.md` |
| 2 | Схема БД (DDL) | ✅ Готово | `migration/001_init.sql` |
| 3 | Скрипт миграции Excel → БД | ✅ Готово | `migration/excel_to_db.py` |
| 4 | FastAPI backend | ✅ Готово | `backend/app/` |
| 5 | Проверка API | ⏳ Требует запуска | — |
| 6 | Frontend: index.html + chart.html | ✅ Готово | `frontend/` |
| 7 | Frontend: category.html | ✅ Готово | `frontend/category.html` |
| 8 | Парсер ЦБ РФ | ✅ Готово | `parsers/cbr.py` |
| 9 | Парсеры ДОМ.РФ, Росстат | ✅ Готово | `parsers/domrf.py`, `parsers/rosstat.py` |
| 10 | GitHub Actions | ✅ Готово | `.github/workflows/` |
| 11 | Продакшн (VPS + Docker) | ⏳ Требует VPS | `docker-compose.prod.yml` |
| 12 | Автодеплой при push в main | ✅ Готово | `.github/workflows/deploy.yml` |

---

## Чеклист первого запуска

### Локально

- [ ] `git clone` и `cp .env.example .env`
- [ ] Создать БД: `psql -U postgres -c "CREATE DATABASE realestate;"`
- [ ] Применить схему: `psql -U postgres -d realestate -f migration/001_init.sql`
- [ ] Положить Excel в `migration/data/`
- [ ] Запустить миграцию: `python migration/excel_to_db.py migration/data/file.xlsx`
- [ ] Запустить API: `cd backend && uvicorn app.main:app --reload --port 8000`
- [ ] Открыть http://localhost:8000/docs и проверить `/api/categories`
- [ ] Открыть frontend: `cd frontend && python -m http.server 8080`
- [ ] Проверить http://localhost:8080 в браузере

### Продакшн

- [ ] Арендовать VPS (2 CPU / 4 GB, Ubuntu 22.04)
- [ ] Установить Docker и Docker Compose на VPS
- [ ] Создать `.env.prod` с продакшн-значениями
- [ ] `docker compose -f docker-compose.prod.yml up -d`
- [ ] Применить SQL-схему
- [ ] Запустить миграцию с указанием продакшн-БД
- [ ] Настроить SSL через certbot
- [ ] Добавить GitHub Secrets (DB_HOST, DB_PASSWORD, SSH_PRIVATE_KEY, VPS_HOST, TELEGRAM_*)
- [ ] Проверить автодеплой: сделать пустой коммит в main

---

## Известные ограничения и TODO

- [ ] Добавить парсеры `domclick.py` и `rosreestr.py`
- [ ] Добавить Alembic для управления миграциями схемы
- [ ] Добавить пагинацию в `/api/categories/{code}/indicators`
- [ ] Настроить `parse-domclick.yml` и `parse-rosreestr.yml` workflows
- [ ] Добавить раздел топ-застройщиков (листы из Excel)
- [ ] Настроить HTTPS / certbot на VPS
- [ ] Добавить robots.txt и sitemap.xml для SEO
