-- ============================================================
-- Схема БД: Статистика рынка жилой недвижимости России
-- ============================================================

-- Источники данных
CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50) UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    base_url    TEXT,
    update_freq VARCHAR(50),
    notes       TEXT
);

INSERT INTO sources (code, name, base_url, update_freq) VALUES
    ('cbr',       'Банк России',   'https://cbr.ru/statistics/bank_sector/mortgage/', 'monthly'),
    ('emiss',     'ЕМИСС',         'https://www.fedstat.ru',                           'monthly'),
    ('domrf',     'ДОМ.РФ',        'https://наш.дом.рф/opendata',                     'daily'),
    ('rosstat',   'Росстат',       'https://rosstat.gov.ru/opendata',                 'monthly'),
    ('domclick',  'Домклик',       'https://domclick.ru',                             'daily'),
    ('sberindex', 'СберИндекс',    'https://sberindex.ru',                            'daily'),
    ('rosreestr', 'Росреестр',     'https://rosreestr.gov.ru/opendata',               'monthly')
ON CONFLICT (code) DO NOTHING;

-- Тематические разделы
CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50) UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    sort_order  INT DEFAULT 0
);

INSERT INTO categories (code, name, sort_order) VALUES
    ('macro',               'Макроэкономика',                1),
    ('supply_volume',       'Объём ввода жилья',             2),
    ('supply_per_capita',   'Ввод жилья на душу населения',  3),
    ('housing_stock',       'Жилищный фонд',                 4),
    ('under_construction',  'Строящееся жильё',              5),
    ('apartments',          'Квартирография',                6),
    ('concentration',       'Концентрация рынка',            7),
    ('prices',              'Цены',                          8),
    ('demand',              'Спрос',                         9),
    ('mortgage_total',      'Ипотека (всего)',               10),
    ('mortgage_primary',    'Ипотека (первичный рынок)',     11),
    ('mortgage_secondary',  'Ипотека (вторичный рынок)',     12),
    ('mortgage_debt',       'Ипотечная задолженность',       13),
    ('mortgage_domclick',   'Ипотека (Домклик)',             14),
    ('mortgage_frankrg',    'Ипотека (Frank RG)',            15),
    ('mortgage_subsidy',    'Льготная ипотека',              16),
    ('mortgage_igs',        'Ипотека на ИЖС',               17)
ON CONFLICT (code) DO NOTHING;

-- Показатели
CREATE TABLE IF NOT EXISTS indicators (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(100) UNIQUE NOT NULL,
    category_id     INT REFERENCES categories(id),
    source_id       INT REFERENCES sources(id),
    name            TEXT NOT NULL,
    unit            TEXT,
    periodicity     VARCHAR(20),
    period_type     VARCHAR(20),
    geo_level       VARCHAR(20) DEFAULT 'russia',
    description     TEXT,
    source_url      TEXT,
    last_updated    TIMESTAMPTZ,
    is_public       BOOLEAN DEFAULT TRUE,
    chart_type      VARCHAR(20) DEFAULT 'line',
    sort_order      INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_indicators_category ON indicators(category_id);

-- Временные ряды
CREATE TABLE IF NOT EXISTS data_points (
    id              BIGSERIAL PRIMARY KEY,
    indicator_id    INT REFERENCES indicators(id) ON DELETE CASCADE,
    period_date     DATE NOT NULL,
    period_label    VARCHAR(50),
    value           NUMERIC(20, 4),
    is_preliminary  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (indicator_id, period_date)
);

CREATE INDEX IF NOT EXISTS idx_data_points_indicator ON data_points(indicator_id, period_date DESC);

-- Materialized view с динамикой
CREATE MATERIALIZED VIEW IF NOT EXISTS data_points_with_dynamics AS
SELECT
    dp.id,
    dp.indicator_id,
    dp.period_date,
    dp.period_label,
    dp.value,
    dp.is_preliminary,
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
        ) != 0
        THEN ROUND(
            (dp.value - LAG(dp.value) OVER (
                PARTITION BY dp.indicator_id, EXTRACT(MONTH FROM dp.period_date)
                ORDER BY dp.period_date
            )) / ABS(LAG(dp.value) OVER (
                PARTITION BY dp.indicator_id, EXTRACT(MONTH FROM dp.period_date)
                ORDER BY dp.period_date
            )) * 100, 2
        )
        ELSE NULL
    END AS yoy_change_pct,
    LAG(dp.value) OVER (
        PARTITION BY dp.indicator_id
        ORDER BY dp.period_date
    ) AS value_prev_period,
    SUM(dp.value) OVER (
        PARTITION BY dp.indicator_id, EXTRACT(YEAR FROM dp.period_date)
        ORDER BY dp.period_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS value_ytd
FROM data_points dp;

CREATE UNIQUE INDEX IF NOT EXISTS ON data_points_with_dynamics (indicator_id, period_date);

-- Лог задач обновления
CREATE TABLE IF NOT EXISTS update_jobs (
    id              SERIAL PRIMARY KEY,
    source_id       INT REFERENCES sources(id),
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          VARCHAR(20),
    rows_upserted   INT,
    error_message   TEXT
);
