-- migration/002_domrf_private_indicators.sql
-- Добавление индикаторов из покупных данных ДОМ.РФ
-- Запускать ОДИН РАЗ перед первым запуском скриптов миграции

-- =============================================================
-- 1. Показатель 3.6 — перенос в раздел «Уровень концентрации»
--    (индикатор уже существует, просто меняем category_id)
-- =============================================================

UPDATE indicators
SET category_id = (SELECT id FROM categories WHERE code = 'concentration')
WHERE code = '3.6';


-- =============================================================
-- 2. Квартирография (раздел apartments)
--    Дочерние индикаторы по комнатности
-- =============================================================

DO $$
DECLARE
    cat_id INT := (SELECT id FROM categories WHERE code = 'apartments');
    src_id INT := (SELECT id FROM sources WHERE code = 'domrf');
BEGIN
    INSERT INTO indicators
        (code, category_id, source_id, name, unit, periodicity, period_type, is_public, chart_type, sort_order)
    VALUES
      -- Количество (для combo-bar с is_public=false на дочерних)
      ('apartments_count_1k',    cat_id, src_id, 'Количество квартир в стройке: 1-комнатные',          'шт.', 'monthly', 'point_in_time', false, 'bar',  10),
      ('apartments_count_2k',    cat_id, src_id, 'Количество квартир в стройке: 2-комнатные',          'шт.', 'monthly', 'point_in_time', false, 'bar',  11),
      ('apartments_count_3k',    cat_id, src_id, 'Количество квартир в стройке: 3-комнатные',          'шт.', 'monthly', 'point_in_time', false, 'bar',  12),
      ('apartments_count_4k',    cat_id, src_id, 'Количество квартир в стройке: 4-комнатные и более',  'шт.', 'monthly', 'point_in_time', false, 'bar',  13),
      ('apartments_count_total', cat_id, src_id, 'Квартирография: количество квартир (всего)',         'шт.', 'monthly', 'point_in_time', true,  'bar',  14),
      -- Средняя площадь
      ('apartments_area_1k',    cat_id, src_id, 'Средняя площадь квартир в стройке: 1-комнатные',         'кв. м', 'monthly', 'point_in_time', false, 'line', 20),
      ('apartments_area_2k',    cat_id, src_id, 'Средняя площадь квартир в стройке: 2-комнатные',         'кв. м', 'monthly', 'point_in_time', false, 'line', 21),
      ('apartments_area_3k',    cat_id, src_id, 'Средняя площадь квартир в стройке: 3-комнатные',         'кв. м', 'monthly', 'point_in_time', false, 'line', 22),
      ('apartments_area_4k',    cat_id, src_id, 'Средняя площадь квартир в стройке: 4-комнатные и более', 'кв. м', 'monthly', 'point_in_time', false, 'line', 23),
      ('apartments_area_total', cat_id, src_id, 'Квартирография: средняя площадь (все типы)',             'кв. м', 'monthly', 'point_in_time', true,  'line', 24),
      -- Структура
      ('apartments_share_1k', cat_id, src_id, 'Структура стройки по комнатности: 1-комнатные',         '%', 'monthly', 'point_in_time', false, 'bar', 30),
      ('apartments_share_2k', cat_id, src_id, 'Структура стройки по комнатности: 2-комнатные',         '%', 'monthly', 'point_in_time', false, 'bar', 31),
      ('apartments_share_3k', cat_id, src_id, 'Структура стройки по комнатности: 3-комнатные',         '%', 'monthly', 'point_in_time', false, 'bar', 32),
      ('apartments_share_4k', cat_id, src_id, 'Структура стройки по комнатности: 4-комнатные и более', '%', 'monthly', 'point_in_time', false, 'bar', 33)
    ON CONFLICT (code) DO NOTHING;
END $$;


-- =============================================================
-- 3. Матрица продаж — новые и пересчитываемые индикаторы
-- =============================================================

DO $$
DECLARE
    cat_demand INT := (SELECT id FROM categories WHERE code = 'demand');
    cat_prices INT := (SELECT id FROM categories WHERE code = 'prices');
    src_domrf  INT := (SELECT id FROM sources WHERE code = 'domrf');
BEGIN
    INSERT INTO indicators
        (code, category_id, source_id, name, unit, periodicity, period_type, is_public, chart_type, sort_order)
    VALUES
      -- Квартиры: новые показатели
      ('apt_budget', cat_demand, src_domrf, 'Средний бюджет сделки с квартирой',          'руб.',    'monthly', 'period', true, 'line', 25),
      ('apt_area',   cat_demand, src_domrf, 'Средняя площадь квартиры в сделке',          'кв. м',   'monthly', 'period', true, 'line', 26),
      -- Машиноместа
      ('mm_count',   cat_demand, src_domrf, 'Количество сделок с машиноместами',           'шт.',     'monthly', 'period', true, 'bar',  30),
      ('mm_price',   cat_prices, src_domrf, 'Средняя цена 1 кв. м машиноместа',           'руб.',    'monthly', 'period', true, 'line', 31),
      ('mm_budget',  cat_prices, src_domrf, 'Средний бюджет машиноместа',                 'руб.',    'monthly', 'period', true, 'line', 32),
      ('mm_area',    cat_demand, src_domrf, 'Средняя площадь машиноместа в сделке',        'кв. м',   'monthly', 'period', true, 'line', 33)
    ON CONFLICT (code) DO NOTHING;
END $$;


-- =============================================================
-- 4. Справка: существующие индикаторы которые ПЕРЕСЧИТЫВАЮТСЯ
--    (не нужно создавать, просто напоминание)
-- =============================================================
-- 4.1  — средняя цена 1 кв. м квартир (уже в БД, данные за 2021+ пересчитаются)
-- 5.8  — количество сделок с квартирами (уже в БД, данные за 2021+ пересчитаются)
-- 3.6  — доля топ-5 застройщиков (уже в БД, все данные будут пересчитаны)
