-- ============================================================
-- migration/004_cleanup.sql
-- Очистка БД перед деплоем на VPS
-- Создан: 2026-05-22
-- См. полный отчёт: migration/004_db_audit_report.md
--
-- ПРИМЕНЕНИЕ:
--   psql -U postgres -d realestate -f migration/004_cleanup.sql
--
-- Затем отдельно:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics;
-- ============================================================

BEGIN;

-- ============================================================
-- СЕКЦИЯ 1 [HIGH]: Убрать легаси-префикс "X.X " из 92 названий
-- code хранится отдельно — дублирование в name засоряет UI и экспорт
-- ============================================================

UPDATE indicators
SET name = REGEXP_REPLACE(name, '^[0-9]+\.[0-9.]+ ', '')
WHERE name ~ '^[0-9]+\.[0-9.]+ ';

-- ============================================================
-- СЕКЦИЯ 2 [HIGH]: Единица измерения для индикатора 5.10
-- "Доступность жилья (отношение зарплаты к стоимости жилья)"
-- Формула: зарплата (руб./мес.) / цена (руб./кв.м) = кв.м на 1 зарплату
-- ============================================================

UPDATE indicators
SET unit = 'кв.м/зарплату'
WHERE code = '5.10' AND unit IS NULL;

-- ============================================================
-- СЕКЦИЯ 3 [HIGH]: CHECK-ограничения на enum-поля indicators
-- Предотвращают запись невалидных значений парсерами/скриптами
-- ============================================================

ALTER TABLE indicators
    ADD CONSTRAINT chk_periodicity
    CHECK (periodicity IN ('monthly', 'annual', 'quarterly'));

ALTER TABLE indicators
    ADD CONSTRAINT chk_period_type
    CHECK (period_type IN ('period', 'point_in_time'));

ALTER TABLE indicators
    ADD CONSTRAINT chk_chart_type
    CHECK (chart_type IN ('line', 'bar', 'area', 'combo'));

-- ============================================================
-- СЕКЦИЯ 4 [MEDIUM]: sort_order companion-индикаторов в macro
-- 1.2.y, 1.3.y — скрытые (is_public=false), мешают sort_order=0
-- вместе с публичными 1.1 и 1.3
-- ============================================================

UPDATE indicators
SET sort_order = 100
WHERE code IN ('1.2.y', '1.3.y');

-- ============================================================
-- СЕКЦИЯ 5 [MEDIUM]: Позиция категории under_construction_domrf
-- Вставляем сразу после under_construction (sort_order=5),
-- перед apartments. Сдвигаем все категории >= 6 на +1.
-- ============================================================

-- Сдвиг (под_construction_domrf исключён — у него уже sort_order=6)
UPDATE categories
SET sort_order = sort_order + 1
WHERE sort_order >= 6 AND code != 'under_construction_domrf';

-- under_construction_domrf остаётся на 6 (теперь это свободная позиция)
-- Результирующий порядок навигации:
--   1 macro | 2 supply_volume | 4 housing_stock | 5 under_construction
--   6 under_construction_domrf | 7 apartments | 8 concentration | 9 prices
--   10 demand | 11-12 mortgage_total/base | ... | 18 mortgage_igs

-- ============================================================
-- СЕКЦИЯ 6 [MEDIUM]: Устранить дублирующиеся названия
--
-- 6a: 3.7 vs uc_dev_activity — одинаковый показатель, разные источники:
--     3.7         = открытые данные ДОМ.РФ (public API / раздел under_construction)
--     uc_dev_activity = платная база ДОМ.РФ (раздел under_construction_domrf)
--
-- 6b: uc_new_active vs uc_new_total — одно название, разный охват проектов
-- ============================================================

UPDATE indicators
SET name = 'Девелоперская активность по текущему строительству (открытые данные ДОМ.РФ)'
WHERE code = '3.7';

UPDATE indicators
SET name = 'Девелоперская активность по текущему строительству (платная база ДОМ.РФ)'
WHERE code = 'uc_dev_activity';

UPDATE indicators
SET name = 'Запуск новых проектов (активные)'
WHERE code = 'uc_new_active';

UPDATE indicators
SET name = 'Запуск новых проектов (все)'
WHERE code = 'uc_new_total';

-- ============================================================
-- СЕКЦИЯ 7 [PENDING]: sort_order для категории demand
-- 6 публичных индикаторов застряли на sort_order=0
-- Раскомментируйте после подтверждения порядка карточек:
-- ============================================================

-- UPDATE indicators SET sort_order = 10  WHERE code = '5.1';       -- ДДУ всего
-- UPDATE indicators SET sort_order = 20  WHERE code = '5.8';       -- квартиры в ДДУ
-- UPDATE indicators SET sort_order = 30  WHERE code = '5.9';       -- темп продаж квартир
-- UPDATE indicators SET sort_order = 35  WHERE code = '5.9.ma12';
-- UPDATE indicators SET sort_order = 40  WHERE code = '5.20';      -- машиноместа в ДДУ
-- UPDATE indicators SET sort_order = 50  WHERE code = '5.22';      -- темп продаж мм
-- UPDATE indicators SET sort_order = 55  WHERE code = '5.22.ma12';
-- UPDATE indicators SET sort_order = 60  WHERE code = 'apt_area';  -- средняя площадь квартиры
-- UPDATE indicators SET sort_order = 70  WHERE code = '5.3';       -- активность первичка
-- UPDATE indicators SET sort_order = 75  WHERE code = '5.4';       -- активность вторичка
-- UPDATE indicators SET sort_order = 80  WHERE code = '5.10';      -- доступность зарплата/цена
-- UPDATE indicators SET sort_order = 90  WHERE code = '5.11';      -- доступность ФЦП
-- UPDATE indicators SET sort_order = 95  WHERE code = '5.21';      -- средняя площадь мм
-- UPDATE indicators SET sort_order = 110 WHERE code = '5.12.33';
-- UPDATE indicators SET sort_order = 111 WHERE code = '5.12.38';
-- UPDATE indicators SET sort_order = 112 WHERE code = '5.13.33';
-- UPDATE indicators SET sort_order = 113 WHERE code = '5.13.38';
-- UPDATE indicators SET sort_order = 114 WHERE code = '5.14.33';
-- UPDATE indicators SET sort_order = 115 WHERE code = '5.14.38';
-- UPDATE indicators SET sort_order = 116 WHERE code = '5.15.33';
-- UPDATE indicators SET sort_order = 117 WHERE code = '5.15.38';
-- UPDATE indicators SET sort_order = 120 WHERE code = 'mm_count';
-- UPDATE indicators SET sort_order = 121 WHERE code = 'mm_area';
-- UPDATE indicators SET sort_order = 130 WHERE code = 'sales_apt_sqm';

-- ============================================================
-- СЕКЦИЯ 8 [PENDING]: sort_order для категории prices
-- 3 публичных индикатора застряли на sort_order=0
-- ============================================================

-- UPDATE indicators SET sort_order = 0   WHERE code = '4.1';        -- ДОМ.РФ первичка
-- UPDATE indicators SET sort_order = 10  WHERE code = '4.4';        -- Росстат агрегат
-- UPDATE indicators SET sort_order = 20  WHERE code = '4.8';        -- машиноместа
-- UPDATE indicators SET sort_order = 30  WHERE code = '4.9';        -- бюджет мм
-- UPDATE indicators SET sort_order = 40  WHERE code = '4.5';        -- вторичка
-- UPDATE indicators SET sort_order = 50  WHERE code = 'apt_budget'; -- бюджет квартиры

-- ============================================================
-- СЕКЦИЯ 9 [PENDING]: Дублирующиеся имена в apartments/under_construction
-- "Количество квартир" — 6 индикаторов в двух разных категориях
-- "Средняя площадь"   — 6 индикаторов в двух разных категориях
-- Добавить контекст в скобках (раскомментировать после решения):
-- ============================================================

-- under_construction (строящееся жильё):
-- UPDATE indicators SET name = 'Количество квартир (строящееся жильё)'
--   WHERE code = '3.13';
-- UPDATE indicators SET name = 'Средняя площадь квартиры (строящееся жильё)'
--   WHERE code = '3.15';

-- apartments (продажи ДОМ.РФ):
-- UPDATE indicators SET name = 'Количество квартир (продажи)'
--   WHERE code = 'apartments_count_total';
-- UPDATE indicators SET name = 'Количество 1-комнатных квартир (продажи)'
--   WHERE code = 'apartments_count_1k';
-- UPDATE indicators SET name = 'Количество 2-комнатных квартир (продажи)'
--   WHERE code = 'apartments_count_2k';
-- UPDATE indicators SET name = 'Количество 3-комнатных квартир (продажи)'
--   WHERE code = 'apartments_count_3k';
-- UPDATE indicators SET name = 'Количество 4+ комнатных квартир (продажи)'
--   WHERE code = 'apartments_count_4k';
-- UPDATE indicators SET name = 'Средняя площадь квартиры (продажи)'
--   WHERE code = 'apartments_area_total';
-- ... (аналогично для apartments_area_1k/2k/3k/4k)

-- ============================================================
-- ИТОГОВЫЕ ПРОВЕРКИ
-- ============================================================

-- 1. Нет легаси-префиксов
SELECT COUNT(*) AS prefixes_remaining
FROM indicators WHERE name ~ '^[0-9]+\.[0-9.]+ ';

-- 2. 5.10 имеет unit
SELECT code, unit FROM indicators WHERE code = '5.10';

-- 3. CHECK-ограничения созданы (должно быть 3)
SELECT conname FROM pg_constraint
WHERE conrelid = 'indicators'::regclass AND contype = 'c'
ORDER BY conname;

-- 4. Нет конфликтов sort_order в categories
SELECT sort_order, array_agg(code ORDER BY id) AS cats
FROM categories
GROUP BY sort_order HAVING COUNT(*) > 1;

-- 5. Порядок категорий после сдвига
SELECT sort_order, code FROM categories ORDER BY sort_order;

-- 6. Дубли названий (должно остаться только apartments_count/area группы)
SELECT name, COUNT(*) AS cnt, string_agg(code, ', ' ORDER BY code) AS codes
FROM indicators
GROUP BY name HAVING COUNT(*) > 1
ORDER BY cnt DESC;

COMMIT;

-- ============================================================
-- ПОСЛЕ ПРИМЕНЕНИЯ (выполнить отдельно):
-- REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics;
-- ============================================================
