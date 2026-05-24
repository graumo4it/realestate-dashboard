-- ============================================================
-- migration/005_market_balance.sql
-- Создание категории «Сбалансированность рынка»
-- Перенос 9 индикаторов из under_construction_domrf
-- Создан: 2026-05-22
--
-- ПРИМЕНЕНИЕ:
--   psql -U postgres -d realestate -f migration/005_market_balance.sql
--   REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics;
-- ============================================================

BEGIN;

-- 1. Освободить sort_order=11 для новой категории
--    (сдвигаем mortgage_total и всё после него)
UPDATE categories
SET sort_order = sort_order + 1
WHERE sort_order >= 11;

-- 2. Создать новую категорию
INSERT INTO categories (code, name, sort_order)
VALUES ('market_balance', 'Сбалансированность рынка', 11);

-- 3. Переместить индикаторы и расставить sort_order
UPDATE indicators
SET
  category_id = (SELECT id FROM categories WHERE code = 'market_balance'),
  sort_order = CASE code
    WHEN 'uc_sold_vs_ready'          THEN 0
    WHEN 'uc_new_vs_input_total'     THEN 10
    WHEN 'uc_new_vs_input_active'    THEN 11
    WHEN 'uc_stock_years_total'      THEN 20
    WHEN 'uc_stock_years_active'     THEN 21
    WHEN 'uc_new_vs_sales_total'     THEN 30
    WHEN 'uc_new_vs_sales_active'    THEN 31
    WHEN 'uc_absorption_total'       THEN 40
    WHEN 'uc_absorption_active'      THEN 41
  END
WHERE code IN (
  'uc_sold_vs_ready',
  'uc_new_vs_input_total',  'uc_new_vs_input_active',
  'uc_stock_years_total',   'uc_stock_years_active',
  'uc_new_vs_sales_total',  'uc_new_vs_sales_active',
  'uc_absorption_total',    'uc_absorption_active'
);

-- ─── Проверки ───────────────────────────────────────────────

-- Все категории в правильном порядке
SELECT sort_order, code, name FROM categories ORDER BY sort_order;

-- Индикаторы по двум затронутым категориям
SELECT c.code AS category, i.code, i.name, i.sort_order
FROM indicators i
JOIN categories c ON i.category_id = c.id
WHERE c.code IN ('under_construction_domrf', 'market_balance')
ORDER BY c.sort_order, i.sort_order;

COMMIT;

-- ============================================================
-- ПОСЛЕ ПРИМЕНЕНИЯ (выполнить отдельно):
-- REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics;
-- ============================================================
