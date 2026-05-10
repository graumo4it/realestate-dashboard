-- =============================================================================
-- ПРАВКИ v1.2 — Переименования индикаторов и разделов
-- Источник: правки.xlsx (правки без скрина: переим. / breadcrumb / раздел)
-- Коды сверены с реальной БД 2026-05-08
-- Применять: psql -d realestate -U postgres -f rename_fixes.sql
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. РАЗДЕЛЫ (categories)
-- ---------------------------------------------------------------------------

UPDATE categories SET name = 'Ввод жилья'
  WHERE code = 'supply_volume';

UPDATE categories SET name = 'Уровень концентрации рынка'
  WHERE code = 'concentration';


-- ---------------------------------------------------------------------------
-- 2. ВВОД ЖИЛЬЯ
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Объём ввода жилья'
  WHERE code = '2.1';

UPDATE indicators SET name = 'Структура ввода жилья'
  WHERE code = '2.3';

UPDATE indicators
  SET name = 'Объем ввода жилья на душу населения'
  WHERE category_id = (SELECT id FROM categories WHERE code = 'supply_per_capita')
    AND name ILIKE '%душу населения%';


-- ---------------------------------------------------------------------------
-- 3. ЖИЛИЩНЫЙ ФОНД
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Доля ветхого и аварийного жилищного фонда'
  WHERE code = '2.13.ext';

UPDATE indicators
  SET name = 'Общая площадь жилых помещений, приходящаяся в среднем на одного жителя (Обеспеченность жилфондом)'
  WHERE code = '2.10';

UPDATE indicators SET name = 'Прибыло жилфонда'
  WHERE code = '2.11';

UPDATE indicators SET name = 'Выбыло жилфонда'
  WHERE code = '2.12';

UPDATE indicators
  SET name = 'Доля жилфонда, обеспеченного всеми видами благоустройства'
  WHERE code = '2.13';


-- ---------------------------------------------------------------------------
-- 4. СТРОЯЩЕЕСЯ ЖИЛЬЁ (Росстат)
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Девелоперская активность по текущему строительству'
  WHERE code = '3.7';


-- ---------------------------------------------------------------------------
-- 5. СТРОЯЩЕЕСЯ ЖИЛЬЁ (ДОМ.РФ) — реальные коды из БД
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Жилая площадь возводимых многоквартирных жилых домов на отчетную дату'
  WHERE code = 'uc_area_total';

UPDATE indicators SET name = 'Жилая площадь МЖД в стадии активного строительства'
  WHERE code = 'uc_area_active';

UPDATE indicators SET name = 'Запуск новых проектов'
  WHERE code IN ('uc_new_total', 'uc_new_active');

UPDATE indicators SET name = 'Отношение запусков и вводов (все проекты)'
  WHERE code = 'uc_new_vs_input_total';

UPDATE indicators SET name = 'Отношение запусков и вводов (активные проекты)'
  WHERE code = 'uc_new_vs_input_active';

UPDATE indicators SET name = 'Запасы строящегося жилья (все проекты)'
  WHERE code = 'uc_stock_years_total';

UPDATE indicators SET name = 'Запасы строящегося жилья (активные проекты)'
  WHERE code = 'uc_stock_years_active';

UPDATE indicators SET name = 'Обеспеченность продаж новыми запусками (все проекты)'
  WHERE code = 'uc_new_vs_sales_total';

UPDATE indicators SET name = 'Обеспеченность продаж новыми запусками (активные проекты)'
  WHERE code = 'uc_new_vs_sales_active';

UPDATE indicators SET name = 'Коэффициент поглощения (все проекты)'
  WHERE code = 'uc_absorption_total';

UPDATE indicators SET name = 'Коэффициент поглощения (активные проекты)'
  WHERE code = 'uc_absorption_active';


-- ---------------------------------------------------------------------------
-- 6. КВАРТИРОГРАФИЯ
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Количество квартир'
  WHERE category_id = (SELECT id FROM categories WHERE code = 'apartments')
    AND name ILIKE '%количество квартир%';

UPDATE indicators SET name = 'Средняя площадь'
  WHERE category_id = (SELECT id FROM categories WHERE code = 'apartments')
    AND name ILIKE '%средняя площадь%';

UPDATE indicators SET name = 'Структура по комнатности'
  WHERE category_id = (SELECT id FROM categories WHERE code = 'apartments')
    AND name ILIKE '%структура по комнатности%';


-- ---------------------------------------------------------------------------
-- 7. УРОВЕНЬ КОНЦЕНТРАЦИИ РЫНКА
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Индекс Херфиндаля-Хиршмана (HHI)'
  WHERE code IN ('3.17', '3.18')
    AND name ILIKE '%концентрации рынка%';

-- Страховка на случай если 3.6 не был переименован ранее
UPDATE indicators SET name = 'Доля топ-5 застройщиков в объёме возводимого жилья'
  WHERE code = '3.6'
    AND name NOT ILIKE '%топ-5%';


-- ---------------------------------------------------------------------------
-- 8. ЦЕНЫ
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Средняя стоимость сделок с жильем в строящихся объектах (ДОМ.РФ)'
  WHERE code = '4.1';

UPDATE indicators SET name = 'Средняя стоимость сделок с жильем (Росстат)'
  WHERE code = '4.4';

UPDATE indicators SET name = 'Средняя стоимость сделок с машиноместами в строящихся объектах (ДОМ.РФ)'
  WHERE code = '4.8';

UPDATE indicators SET name = 'Средний бюджет проданных машиномест в строящихся объектах (ДОМ.РФ)'
  WHERE code = '4.9';

-- apt_budget: перенести в раздел Цены + переименовать + единица измерения
UPDATE indicators
  SET name = 'Средний бюджет проданных квартир в строящихся объектах (ДОМ.РФ)',
      category_id = (SELECT id FROM categories WHERE code = 'prices'),
      unit = 'млн руб.'
  WHERE code = 'apt_budget';


-- ---------------------------------------------------------------------------
-- 9. СПРОС
-- ---------------------------------------------------------------------------

UPDATE indicators
  SET name = 'Общее количество ДДУ (Росреестр)',
      chart_type = 'bar'
  WHERE code = '5.1';

UPDATE indicators SET name = 'Количество сделок по продаже квартир на первичном рынке'
  WHERE code = '5.8';

UPDATE indicators SET name = 'Количество сделок по продаже машиномест на первичном рынке'
  WHERE code = '5.20';

UPDATE indicators SET name = 'Средняя площадь сделок по продаже машиномест на первичном рынке'
  WHERE code = '5.21';

UPDATE indicators
  SET name = 'Темп продаж квартир на первичном рынке',
      unit = 'ед./мес.'
  WHERE code = '5.9';

UPDATE indicators
  SET name = 'Доступность жилья (отношение зарплаты к стоимости жилья)',
      unit = NULL
  WHERE code = '5.10';

UPDATE indicators
  SET name = 'Доступность жилья (методика ФЦП «Жилище»)',
      unit = 'лет'
  WHERE code = '5.11';

UPDATE indicators
  SET name = 'Скорость удовлетворения потребности в жилье при текущем объеме ввода'
  WHERE code = '5.13';

UPDATE indicators
  SET name = 'Скорость удовлетворения реальной потребности в жилье при текущем объеме ввода'
  WHERE code = '5.15';

UPDATE indicators
  SET name = 'Активность спроса на первичном рынке',
      unit = 'сделок/тыс. чел.'
  WHERE code = '5.3';

UPDATE indicators SET name = 'Средняя площадь сделок по продаже квартир на первичном рынке'
  WHERE code = 'apt_area_deal';


-- ---------------------------------------------------------------------------
-- 10. ИПОТЕКА — ОСНОВНЫЕ ДАННЫЕ (код категории в БД: mortgage_base)
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Количество выданных ипотечных кредитов'
  WHERE code = '6.7';

UPDATE indicators SET name = 'Объём выданных ипотечных кредитов'
  WHERE code = '6.8';

UPDATE indicators SET name = 'Средневзвешенная ставка по ипотеке'
  WHERE code = '6.3';

UPDATE indicators SET name = 'Средневзвешенный срок ипотечного кредита'
  WHERE code = '6.4';

UPDATE indicators SET name = 'Средний размер ипотечного кредита'
  WHERE code = '6.5';

UPDATE indicators SET name = 'Средний ежемесячный платёж по ипотеке'
  WHERE code = '6.6';


-- ---------------------------------------------------------------------------
-- 11. ИПОТЕКА — ЗАДОЛЖЕННОСТЬ (реальные коды: 6.19/6.20/6.21 = «всего»)
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Объём задолженности по ипотеке'
  WHERE code = '6.19';

UPDATE indicators SET name = 'Объём просроченной задолженности по ипотеке'
  WHERE code = '6.20';

UPDATE indicators SET name = 'Доля просроченной задолженности по ипотеке'
  WHERE code = '6.21';


-- ---------------------------------------------------------------------------
-- 12. ИПОТЕКА ИЖС
-- ---------------------------------------------------------------------------

UPDATE indicators SET name = 'Количество ипотечных кредитов на ИЖС'
  WHERE code = '6.70';

UPDATE indicators SET name = 'Объём ипотечных кредитов на ИЖС'
  WHERE code = '6.71';

UPDATE indicators SET name = 'Средневзвешенная ставка по ипотеке на ИЖС'
  WHERE code = '6.72';

UPDATE indicators SET name = 'Средневзвешенный срок ипотеки на ИЖС'
  WHERE code = '6.73';

UPDATE indicators SET name = 'Средний размер кредита по ипотеке на ИЖС'
  WHERE code = '6.74';

-- Исправляем опечатку из правки (там было «Количество...» вместо «платёж»)
UPDATE indicators SET name = 'Средний ежемесячный платёж по ипотеке на ИЖС'
  WHERE code = '6.75';


-- ---------------------------------------------------------------------------
-- 13. УДАЛИТЬ ДУБЛИ
-- ---------------------------------------------------------------------------

DELETE FROM data_points
  WHERE indicator_id IN (
    SELECT id FROM indicators
    WHERE name ILIKE '%Средняя цена 1 кв. м машиноместа%'
      AND code NOT IN ('4.8', '4.9')
  );

DELETE FROM indicators
  WHERE name ILIKE '%Средняя цена 1 кв. м машиноместа%'
    AND code NOT IN ('4.8', '4.9');

DELETE FROM data_points
  WHERE indicator_id IN (
    SELECT id FROM indicators
    WHERE name ILIKE '%Средний бюджет машиноместа%'
  );

DELETE FROM indicators
  WHERE name ILIKE '%Средний бюджет машиноместа%';


-- ---------------------------------------------------------------------------
-- ФИНАЛ
-- ---------------------------------------------------------------------------

REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics;

COMMIT;


-- ---------------------------------------------------------------------------
-- ПРОВЕРКА (запустить после коммита)
-- ---------------------------------------------------------------------------
SELECT code, name, unit
FROM indicators
WHERE code IN (
  '2.1','2.3','2.10','2.11','2.12','2.13','2.13.ext',
  '3.6','3.7','3.17','3.18',
  '4.1','4.4','4.8','4.9','apt_budget',
  '5.1','5.3','5.8','5.9','5.10','5.11','5.13','5.15','5.20','5.21',
  'apt_area_deal',
  '6.3','6.4','6.5','6.6','6.7','6.8',
  '6.19','6.20','6.21',
  '6.70','6.71','6.72','6.73','6.74','6.75',
  'uc_area_total','uc_area_active',
  'uc_new_total','uc_new_active',
  'uc_new_vs_input_total','uc_new_vs_input_active',
  'uc_stock_years_total','uc_stock_years_active',
  'uc_new_vs_sales_total','uc_new_vs_sales_active',
  'uc_absorption_total','uc_absorption_active'
)
ORDER BY code;
