-- =============================================================================
-- migration/001_init.sql
-- Схема PostgreSQL для дашборда «Статистика рынка жилой недвижимости России»
-- =============================================================================
-- Применить: psql -U postgres -d realestate -f migration/001_init.sql
-- =============================================================================

-- -----------------------------------------------------------------------------
-- РАСШИРЕНИЯ
-- -----------------------------------------------------------------------------
-- pg_trgm нужен для полнотекстового поиска по названиям показателей (эндпоинт /api/search)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- 1. SOURCES — источники данных
-- -----------------------------------------------------------------------------
CREATE TABLE sources (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50) UNIQUE NOT NULL,
    name        TEXT        NOT NULL,
    base_url    TEXT,
    update_freq VARCHAR(50),   -- 'daily' | 'weekly' | 'monthly' | 'quarterly'
    notes       TEXT
);

-- -----------------------------------------------------------------------------
-- 2. CATEGORIES — тематические разделы верхнего уровня навигации
-- -----------------------------------------------------------------------------
CREATE TABLE categories (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50) UNIQUE NOT NULL,
    name        TEXT        NOT NULL,
    sort_order  INT         DEFAULT 0
);

-- -----------------------------------------------------------------------------
-- 3. INDICATORS — показатели (метаданные временного ряда)
-- -----------------------------------------------------------------------------
CREATE TABLE indicators (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(100) UNIQUE NOT NULL,   -- '6.1', '4.1' и т.д.
    category_id     INT REFERENCES categories(id),
    source_id       INT REFERENCES sources(id),
    name            TEXT NOT NULL,
    unit            TEXT,           -- 'ед.', 'млн руб.', '%', 'кв. м', 'руб.'
    periodicity     VARCHAR(20),    -- 'monthly' | 'annual'

    -- period_type определяет семантику значения и способ расчёта динамики:
    --   'period'        — значение относится к ПРОМЕЖУТКУ времени
    --                     (выдача ипотеки за месяц, ввод жилья за квартал).
    --                     YoY = тот же месяц/год прошлого периода.
    --   'point_in_time' — значение зафиксировано НА конкретную дату
    --                     (остаток задолженности, объём строящегося жилья).
    --                     YoY = та же дата прошлого года.
    -- Оба типа используют одинаковые оконные функции LAG() — различие
    -- важно для бизнес-логики API и подписей на графике.
    period_type     VARCHAR(20),    -- 'period' | 'point_in_time'

    geo_level       VARCHAR(20) DEFAULT 'russia',  -- 'russia' | 'federal_district' | 'region'
    description     TEXT,
    source_url      TEXT,
    last_updated    TIMESTAMPTZ,
    is_public       BOOLEAN     DEFAULT TRUE,
    chart_type      VARCHAR(20) DEFAULT 'line',    -- 'line' | 'bar' | 'area' | 'combo'
    sort_order      INT         DEFAULT 0
);

-- -----------------------------------------------------------------------------
-- 4. DATA_POINTS — временные ряды (только абсолютные значения)
-- -----------------------------------------------------------------------------
-- Дизайн-решение: хранятся ИСКЛЮЧИТЕЛЬНО абсолютные значения.
-- YoY, MoM, YTD — производные метрики, рассчитываемые через materialized view
-- data_points_with_dynamics. Это:
--   а) исключает рассинхрон при ретроспективных правках источников;
--   б) упрощает логику парсеров (только UPSERT абсолютного значения);
--   в) позволяет пересчитать всю динамику одной командой REFRESH MATERIALIZED VIEW.
CREATE TABLE data_points (
    id              BIGSERIAL PRIMARY KEY,
    indicator_id    INT     REFERENCES indicators(id) ON DELETE CASCADE,
    period_date     DATE    NOT NULL,       -- первый день периода: 2024-01-01 = январь 2024 / год 2024
    period_label    VARCHAR(50),            -- 'Январь 2024', '2024', 'Q1 2024' — для отображения
    value           NUMERIC(20, 4),         -- NULL означает отсутствие данных (не 0!)
    is_preliminary  BOOLEAN DEFAULT FALSE,  -- TRUE = предварительные/оперативные данные Росстата
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (indicator_id, period_date)
);

-- -----------------------------------------------------------------------------
-- 5. DATA_POINTS_WITH_DYNAMICS — materialized view с производными метриками
-- -----------------------------------------------------------------------------
-- Пересчитывать после каждого обновления данных:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics;
-- Ключевые решения:
--   • YoY-динамика: LAG() PARTITION BY (indicator_id, MONTH) — берёт то же
--     календарное месяц/год прошлого года независимо от пропусков в ряду.
--   • MoM: LAG() PARTITION BY indicator_id — предыдущая точка ряда.
--   • YTD: SUM() OVER PARTITION BY (indicator_id, YEAR) — накопленный итог
--     с начала года. Для point_in_time показателей YTD семантически
--     не имеет смысла, но вреда не причиняет; API сам решает, возвращать ли его.
--   • Коэффициент yoy_change = (value - prev) / abs(prev) — без умножения на 100,
--     чтобы API мог отдавать как коэффициент (0.15) или процент (15%) по запросу.
CREATE MATERIALIZED VIEW data_points_with_dynamics AS
SELECT
    dp.id,
    dp.indicator_id,
    dp.period_date,
    dp.period_label,
    dp.value,
    dp.is_preliminary,

    -- -------------------------------------------------------------------------
    -- YoY: значение того же периода прошлого года
    -- PARTITION BY indicator_id + EXTRACT(MONTH) гарантирует, что LAG идёт
    -- только внутри одного календарного месяца, а не перескакивает через месяцы.
    -- Для годовых рядов (periodicity='annual') MONTH всегда = 1, поэтому работает
    -- корректно — берётся предыдущий год.
    -- -------------------------------------------------------------------------
    LAG(dp.value) OVER (
        PARTITION BY dp.indicator_id, EXTRACT(MONTH FROM dp.period_date)
        ORDER BY dp.period_date
    ) AS value_prev_year,

    CASE
        WHEN LAG(dp.value) OVER (
                 PARTITION BY dp.indicator_id, EXTRACT(MONTH FROM dp.period_date)
                 ORDER BY dp.period_date
             ) IS NOT NULL
         AND LAG(dp.value) OVER (
                 PARTITION BY dp.indicator_id, EXTRACT(MONTH FROM dp.period_date)
                 ORDER BY dp.period_date
             ) <> 0
        THEN (
            dp.value
            - LAG(dp.value) OVER (
                  PARTITION BY dp.indicator_id, EXTRACT(MONTH FROM dp.period_date)
                  ORDER BY dp.period_date
              )
        ) / ABS(
            LAG(dp.value) OVER (
                PARTITION BY dp.indicator_id, EXTRACT(MONTH FROM dp.period_date)
                ORDER BY dp.period_date
            )
        )
        ELSE NULL
    END AS yoy_change,   -- коэффициент: 0.15 = +15%

    -- -------------------------------------------------------------------------
    -- MoM: значение предыдущего периода (месяца)
    -- -------------------------------------------------------------------------
    LAG(dp.value) OVER (
        PARTITION BY dp.indicator_id
        ORDER BY dp.period_date
    ) AS value_prev_period,

    -- -------------------------------------------------------------------------
    -- YTD: накопленный итог с начала года
    -- Актуален для показателей period_type = 'period' (паттерн B-cum):
    -- ввод жилья, выдача ипотеки, сделки. API решает, отдавать ли это поле,
    -- основываясь на indicators.period_type.
    -- -------------------------------------------------------------------------
    SUM(dp.value) OVER (
        PARTITION BY dp.indicator_id, EXTRACT(YEAR FROM dp.period_date)
        ORDER BY dp.period_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS value_ytd

FROM data_points dp;

-- Уникальный индекс на materialized view — обязателен для CONCURRENTLY REFRESH
CREATE UNIQUE INDEX ON data_points_with_dynamics (indicator_id, period_date);

-- -----------------------------------------------------------------------------
-- 6. UPDATE_JOBS — лог запусков парсеров
-- -----------------------------------------------------------------------------
CREATE TABLE update_jobs (
    id              SERIAL PRIMARY KEY,
    source_id       INT REFERENCES sources(id),
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          VARCHAR(20),   -- 'running' | 'success' | 'error'
    rows_upserted   INT,
    error_message   TEXT
);

-- -----------------------------------------------------------------------------
-- 7. ИНДЕКСЫ
-- -----------------------------------------------------------------------------
-- Основной индекс для выборки временного ряда по показателю
CREATE INDEX idx_data_points_indicator
    ON data_points(indicator_id, period_date DESC);

-- Индекс для фильтрации показателей по категории
CREATE INDEX idx_indicators_category
    ON indicators(category_id);

-- GIN-индекс для полнотекстового поиска (эндпоинт GET /api/search?q=...)
-- pg_trgm позволяет искать подстроки, устойчив к опечаткам через similarity()
CREATE INDEX idx_indicators_name_trgm
    ON indicators USING gin(name gin_trgm_ops);

-- -----------------------------------------------------------------------------
-- 8. НАЧАЛЬНЫЕ ДАННЫЕ: sources
-- -----------------------------------------------------------------------------
INSERT INTO sources (code, name, base_url, update_freq, notes) VALUES
    ('cbr',       'Банк России',  'https://cbr.ru',              'monthly', 'Ипотечная статистика публикуется в виде Excel-файлов'),
    ('rosstat',   'Росстат',      'https://rosstat.gov.ru',       'monthly', 'Ввод жилья, цены, жилфонд'),
    (('domrf', 'ДОМ.РФ', 'https://наш.дом.рф', 'daily',   'Строящееся жильё, цены по ДДУ, ИХХ'),
    ('domclick',  'Домклик',      'https://domclick.ru',          'daily',   'Заявки и выдачи ипотеки'),
    ('rosreestr', 'Росреестр',    'https://rosreestr.gov.ru',     'monthly', 'Сделки ДДУ и купли-продажи');

-- -----------------------------------------------------------------------------
-- 9. НАЧАЛЬНЫЕ ДАННЫЕ: categories
-- -----------------------------------------------------------------------------
INSERT INTO categories (code, name, sort_order) VALUES
    ('macro',               'Макроданные',               1),
    ('supply_volume',       'Объём ввода жилья',          2),
    ('supply_per_capita',   'Ввод на душу населения',     3),
    ('housing_stock',       'Жилищный фонд',              4),
    ('under_construction',  'Строящееся жильё',           5),
    ('apartments',          'Квартирография',             6),
    ('concentration',       'Концентрация рынка',         7),
    ('prices',              'Цены',                       8),
    ('demand',              'Спрос',                      9),
    ('mortgage_total',      'Ипотека (всего)',            10),
    ('mortgage_primary',    'Ипотека (первичный рынок)', 11),
    ('mortgage_secondary',  'Ипотека (вторичный рынок)', 12),
    ('mortgage_debt',       'Задолженность по ипотеке',  13),
    ('mortgage_domclick',   'Ипотека (Домклик)',          14),
    ('mortgage_frankrg',    'Ипотека (Frank RG)',         15),
    ('mortgage_subsidy',    'Льготная ипотека',           16),
    ('mortgage_igs',        'Ипотека на ИЖС',            17);

-- =============================================================================
-- Применить:
--   psql -U postgres -d realestate -f migration/001_init.sql
--
-- После первого наполнения данными выполнить:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics;
--
-- При каждом обновлении данных парсерами повторять REFRESH.
-- Можно добавить в планировщик или вызывать в конце каждого парсера.
-- =============================================================================
