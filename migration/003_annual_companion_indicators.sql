-- Годовые двойники квартальных показателей Росстата.
-- is_public = false → не отображаются в списках категорий,
-- но доступны через /api/indicators/{code}/data и /api/multi/data.
-- Используются chart.html в режиме "Год" для показа официальных годовых значений
-- вместо расчётного среднего из четырёх кварталов.

INSERT INTO indicators
  (code, category_id, source_id, name, unit, periodicity, period_type, is_public, chart_type, sort_order)
VALUES
  ('1.2.y', 1, 4,
   'Среднедушевые денежные доходы населения (годовые)',
   'руб. / мес.', 'annual', 'period', false, 'line', 0),
  ('1.3.y', 1, 4,
   'Среднемесячная номинальная начисленная заработная плата (годовая)',
   'руб.', 'annual', 'period', false, 'line', 0)
ON CONFLICT (code) DO NOTHING;
