-- 006_is_calculated.sql
-- Добавляет флаг is_calculated в таблицу indicators
-- Применить: psql -U postgres -d realestate -f migration/006_is_calculated.sql

ALTER TABLE indicators
    ADD COLUMN IF NOT EXISTS is_calculated boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN indicators.is_calculated IS
    'true = значение вычисляется скриптом migration/calc_*.py, не парсером';

-- Расчётные показатели
UPDATE indicators SET is_calculated = true
WHERE code IN (
    '2.10',                                -- calc_housing_provision.py
    '3.5',                                 -- calc_avg_apt_area.py
    '3.7',                                 -- calc_developer_activity.py
    '5.3',                                 -- calc_demand_activity.py
    '5.9',  '5.9.ma12',                    -- calc_sales_pace.py
    '5.10',                                -- calc_affordability.py
    '5.11',                                -- calc_affordability_fcp.py
    '5.12.33', '5.12.38',                  -- calc_housing_need.py
    '5.13.33', '5.13.38',
    '5.14.33', '5.14.38',
    '5.15.33', '5.15.38',
    '5.22',  '5.22.ma12'                   -- calc_sales_pace_mm.py
);

-- Проверка
SELECT code, name, is_calculated
FROM indicators
WHERE is_calculated = true
ORDER BY code;
