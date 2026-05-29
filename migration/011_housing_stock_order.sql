-- Move the legacy dilapidated/emergency housing stock share to the end of
-- the housing_stock category. The row is historical only (2006-2015), so it
-- should not lead the current housing-stock section.

UPDATE indicators
SET sort_order = 99
WHERE code = '2.13.ext';
