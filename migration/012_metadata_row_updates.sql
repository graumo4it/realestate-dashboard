-- Metadata row corrections for indicator pages.
-- Apply: psql -U postgres -d realestate -f migration/012_metadata_row_updates.sql

-- Population and paid UC developer activity are stated at the beginning of
-- the reporting period.
UPDATE indicators
SET period_type = 'period_start'
WHERE code IN ('1.1', 'uc_dev_activity');

-- Demand activity is a calculated indicator, not a direct Rosreestr source.
UPDATE indicators
SET source_id = (SELECT id FROM sources WHERE code = 'calc')
WHERE code = '5.3';

-- Housing need/pace indicators describe the state at the end of the annual
-- reporting period used in the calculation.
UPDATE indicators
SET period_type = 'period_end'
WHERE code IN (
  '5.12.33','5.12.38',
  '5.13.33','5.13.38',
  '5.14.33','5.14.38',
  '5.15.33','5.15.38'
);

-- Subsidy mortgage section uses DOM.RF as the published source for metadata.
UPDATE indicators
SET source_id = (SELECT id FROM sources WHERE code = 'domrf')
WHERE category_id = (SELECT id FROM categories WHERE code = 'mortgage_subsidy');
