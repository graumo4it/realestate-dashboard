-- migration/008_subsidy_detail.sql
-- 66 новых индикаторов категории mortgage_subsidy (все is_public=false)
--
-- Блок А (01_02_05) — Характеристики кредитов:    коды 6.46.x–6.51.x, sort_order 100–141
-- Блок Б (01_02_03) — Цели кредитования:          коды 6.52.x–6.57.x, sort_order 200–217
-- Блок В (01_02_04) — Типы семей Семейной ипотеки: коды 6.58.1–6.58.6,  sort_order 300–305

INSERT INTO indicators
  (code, name, unit, chart_type, periodicity, period_type,
   is_public, is_calculated, category_id, source_id, sort_order)
VALUES

-- ================================================================
-- БЛОК А: Характеристики кредитов (01_02_05)
-- 6 программ × 7 метрик = 42 индикатора, sort_order 100–141
-- ================================================================

-- 6.46 — Все программы (100–106)
('6.46.1', 'Средняя сумма кредита (Все программы)',            'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 100),
('6.46.2', 'Средневзвешенная ставка (Все программы)',           '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 101),
('6.46.3', 'Собственные средства заёмщика (Все программы)',     '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 102),
('6.46.4', 'Средний срок кредита (Все программы)',              'мес.',      'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 103),
('6.46.5', 'Средняя стоимость помещения (Все программы)',       'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 104),
('6.46.6', 'Средняя площадь (Все программы)',                  'м²',        'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 105),
('6.46.7', 'Средняя стоимость 1 м² (Все программы)',           'тыс. руб.', 'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 106),

-- 6.47 — Льготная ипотека (107–113)
('6.47.1', 'Средняя сумма кредита (Льготная ипотека)',          'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 107),
('6.47.2', 'Средневзвешенная ставка (Льготная ипотека)',        '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 108),
('6.47.3', 'Собственные средства заёмщика (Льготная ипотека)', '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 109),
('6.47.4', 'Средний срок кредита (Льготная ипотека)',           'мес.',      'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 110),
('6.47.5', 'Средняя стоимость помещения (Льготная ипотека)',    'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 111),
('6.47.6', 'Средняя площадь (Льготная ипотека)',               'м²',        'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 112),
('6.47.7', 'Средняя стоимость 1 м² (Льготная ипотека)',        'тыс. руб.', 'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 113),

-- 6.48 — Семейная ипотека (114–120)
('6.48.1', 'Средняя сумма кредита (Семейная ипотека)',          'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 114),
('6.48.2', 'Средневзвешенная ставка (Семейная ипотека)',        '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 115),
('6.48.3', 'Собственные средства заёмщика (Семейная ипотека)', '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 116),
('6.48.4', 'Средний срок кредита (Семейная ипотека)',           'мес.',      'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 117),
('6.48.5', 'Средняя стоимость помещения (Семейная ипотека)',    'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 118),
('6.48.6', 'Средняя площадь (Семейная ипотека)',               'м²',        'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 119),
('6.48.7', 'Средняя стоимость 1 м² (Семейная ипотека)',        'тыс. руб.', 'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 120),

-- 6.49 — ДВ и Арктика (121–127)
('6.49.1', 'Средняя сумма кредита (ДВ и Арктика)',             'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 121),
('6.49.2', 'Средневзвешенная ставка (ДВ и Арктика)',           '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 122),
('6.49.3', 'Собственные средства заёмщика (ДВ и Арктика)',    '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 123),
('6.49.4', 'Средний срок кредита (ДВ и Арктика)',              'мес.',      'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 124),
('6.49.5', 'Средняя стоимость помещения (ДВ и Арктика)',       'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 125),
('6.49.6', 'Средняя площадь (ДВ и Арктика)',                  'м²',        'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 126),
('6.49.7', 'Средняя стоимость 1 м² (ДВ и Арктика)',           'тыс. руб.', 'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 127),

-- 6.50 — IT ипотека (128–134)
('6.50.1', 'Средняя сумма кредита (IT ипотека)',               'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 128),
('6.50.2', 'Средневзвешенная ставка (IT ипотека)',             '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 129),
('6.50.3', 'Собственные средства заёмщика (IT ипотека)',       '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 130),
('6.50.4', 'Средний срок кредита (IT ипотека)',                'мес.',      'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 131),
('6.50.5', 'Средняя стоимость помещения (IT ипотека)',         'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 132),
('6.50.6', 'Средняя площадь (IT ипотека)',                    'м²',        'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 133),
('6.50.7', 'Средняя стоимость 1 м² (IT ипотека)',             'тыс. руб.', 'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 134),

-- 6.51 — Отдельные регионы (135–141)
('6.51.1', 'Средняя сумма кредита (Отдельные регионы)',        'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 135),
('6.51.2', 'Средневзвешенная ставка (Отдельные регионы)',      '%',         'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 136),
('6.51.3', 'Собственные средства заёмщика (Отдельные регионы)', '%',       'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 137),
('6.51.4', 'Средний срок кредита (Отдельные регионы)',         'мес.',      'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 138),
('6.51.5', 'Средняя стоимость помещения (Отдельные регионы)',  'млн руб.',  'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 139),
('6.51.6', 'Средняя площадь (Отдельные регионы)',             'м²',        'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 140),
('6.51.7', 'Средняя стоимость 1 м² (Отдельные регионы)',      'тыс. руб.', 'line', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 141),

-- ================================================================
-- БЛОК Б: Цели кредитования (01_02_03)
-- 6 программ × 3 цели = 18 индикаторов, sort_order 200–217
-- ================================================================

-- 6.52 — Все программы (200–202)
('6.52.1', 'Кредиты по ДДУ (Все программы)',      'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 200),
('6.52.2', 'Кредиты на ИЖС (Все программы)',       'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 201),
('6.52.3', 'Кредиты на вторичку (Все программы)',  'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 202),

-- 6.53 — Льготная ипотека (203–205)
('6.53.1', 'Кредиты по ДДУ (Льготная ипотека)',    'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 203),
('6.53.2', 'Кредиты на ИЖС (Льготная ипотека)',    'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 204),
('6.53.3', 'Кредиты на вторичку (Льготная ипотека)', 'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 205),

-- 6.54 — Семейная ипотека (206–208)
('6.54.1', 'Кредиты по ДДУ (Семейная ипотека)',    'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 206),
('6.54.2', 'Кредиты на ИЖС (Семейная ипотека)',    'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 207),
('6.54.3', 'Кредиты на вторичку (Семейная ипотека)', 'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 208),

-- 6.55 — ДВ и Арктика (209–211)
('6.55.1', 'Кредиты по ДДУ (ДВ и Арктика)',       'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 209),
('6.55.2', 'Кредиты на ИЖС (ДВ и Арктика)',       'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 210),
('6.55.3', 'Кредиты на вторичку (ДВ и Арктика)',  'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 211),

-- 6.56 — IT ипотека (212–214)
('6.56.1', 'Кредиты по ДДУ (IT ипотека)',         'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 212),
('6.56.2', 'Кредиты на ИЖС (IT ипотека)',         'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 213),
('6.56.3', 'Кредиты на вторичку (IT ипотека)',    'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 214),

-- 6.57 — Отдельные регионы (215–217)
('6.57.1', 'Кредиты по ДДУ (Отдельные регионы)',  'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 215),
('6.57.2', 'Кредиты на ИЖС (Отдельные регионы)',  'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 216),
('6.57.3', 'Кредиты на вторичку (Отдельные регионы)', 'шт.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 217),

-- ================================================================
-- БЛОК В: Типы семей Семейной ипотеки (01_02_04)
-- 6 индикаторов, sort_order 300–305
-- ================================================================

-- Количество кредитов, шт. (300–302)
('6.58.1', 'Семьи с ребёнком до 7 лет (количество, Семейная ипотека)',   'шт.',      'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 300),
('6.58.2', 'Семьи с детьми 7–18 лет (количество, Семейная ипотека)',     'шт.',      'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 301),
('6.58.3', 'Дети с инвалидностью (количество, Семейная ипотека)',         'шт.',      'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 302),

-- Объём кредитов, млн руб. (303–305)
('6.58.4', 'Семьи с ребёнком до 7 лет (объём, Семейная ипотека)',        'млн руб.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 303),
('6.58.5', 'Семьи с детьми 7–18 лет (объём, Семейная ипотека)',          'млн руб.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 304),
('6.58.6', 'Дети с инвалидностью (объём, Семейная ипотека)',              'млн руб.', 'bar', 'monthly', 'period', false, false, (SELECT id FROM categories WHERE code='mortgage_subsidy'), (SELECT id FROM sources WHERE code='cbr'), 305);
