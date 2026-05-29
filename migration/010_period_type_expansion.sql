-- Migration 010: expand period_type from 2 values to 4
-- period       → за период (flow data, unchanged)
-- period_start → на начало отчётного периода (stocks measured at period start)
-- period_end   → на конец отчётного периода  (stocks measured at period end)
-- on_date      → на дату                     (snapshot / ratio indicators)

BEGIN;

-- 1. Drop old CHECK, add new one with all 5 values (keep point_in_time for safety during migration)
ALTER TABLE indicators DROP CONSTRAINT chk_period_type;
ALTER TABLE indicators ADD CONSTRAINT chk_period_type CHECK (
  period_type = ANY(ARRAY['period','period_start','period_end','on_date','point_in_time'])
);

-- 2. Reclassify existing point_in_time indicators

-- period_start: на начало отчётного периода
-- under_construction (3.x), concentration (3.x), mortgage_debt (6.19–6.27)
UPDATE indicators SET period_type = 'period_start'
WHERE code IN (
  '1.1',
  '3.1','3.2','3.3','3.4','3.5','3.7',
  '3.6','3.17','3.18','3.19',
  'uc_dev_activity',
  '6.19','6.20','6.21','6.22','6.23','6.24','6.25','6.26','6.27'
);

-- period_end: на конец отчётного периода
-- housing_stock (2.9, 2.13, 2.13.ext), market ratios (uc_absorption, uc_new_vs_*)
-- + 2.10 (housing provision — currently period, reclassify to period_end)
UPDATE indicators SET period_type = 'period_end'
WHERE code IN (
  '2.9','2.13','2.13.ext',
  'uc_absorption_active','uc_absorption_total',
  'uc_new_vs_input_active','uc_new_vs_input_total',
  'uc_new_vs_sales_active','uc_new_vs_sales_total',
  '2.10'
);

-- on_date: на дату
-- apartments, uc_stock, under_construction_domrf, uc_sold_vs_ready
UPDATE indicators SET period_type = 'on_date'
WHERE code IN (
  'apartments_area_1k','apartments_area_2k','apartments_area_3k','apartments_area_4k','apartments_area_total',
  'apartments_count_1k','apartments_count_2k','apartments_count_3k','apartments_count_4k','apartments_count_total',
  'apartments_share_1k','apartments_share_2k','apartments_share_3k','apartments_share_4k',
  'uc_stock_years_active','uc_stock_years_total',
  'uc_area_active','uc_area_total',
  'uc_sold_vs_ready'
);

-- 3. Verify no point_in_time remain (should return 0 rows)
DO $$
DECLARE cnt int;
BEGIN
  SELECT COUNT(*) INTO cnt FROM indicators WHERE period_type = 'point_in_time';
  IF cnt > 0 THEN
    RAISE EXCEPTION 'Migration incomplete: % indicators still have period_type=point_in_time', cnt;
  END IF;
END $$;

-- 4. Remove point_in_time from CHECK now that it's unused
ALTER TABLE indicators DROP CONSTRAINT chk_period_type;
ALTER TABLE indicators ADD CONSTRAINT chk_period_type CHECK (
  period_type = ANY(ARRAY['period','period_start','period_end','on_date'])
);

COMMIT;
