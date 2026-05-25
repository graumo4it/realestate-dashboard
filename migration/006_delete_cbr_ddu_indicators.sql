-- 006_delete_cbr_ddu_indicators.sql
-- Удаление индикаторов 6.46–6.67.1 (ЦБ РФ субсидии по ДДУ)
-- Причина: нет автоматического источника обновления данных,
-- показатели устарели (данные до 10.2024–02.2026 в зависимости от кода),
-- не используются ни в одной комбо-странице.

BEGIN;

-- Удаляем данные
DELETE FROM data_points
WHERE indicator_id IN (
    SELECT id FROM indicators
    WHERE code IN (
        '6.46','6.47','6.48','6.49','6.50','6.51',
        '6.52','6.53','6.54','6.55','6.56','6.57',
        '6.58','6.59','6.60','6.61','6.62','6.63',
        '6.64','6.65','6.66','6.67','6.67.1'
    )
);

-- Удаляем индикаторы
DELETE FROM indicators
WHERE code IN (
    '6.46','6.47','6.48','6.49','6.50','6.51',
    '6.52','6.53','6.54','6.55','6.56','6.57',
    '6.58','6.59','6.60','6.61','6.62','6.63',
    '6.64','6.65','6.66','6.67','6.67.1'
);

-- Также удаляем mm_count и mm_area (они заменены кодами 5.20/5.21 через migrate_sales_matrix.py)
DELETE FROM data_points WHERE indicator_id IN (
    SELECT id FROM indicators WHERE code IN ('mm_count','mm_area')
);
DELETE FROM indicators WHERE code IN ('mm_count','mm_area');

COMMIT;
