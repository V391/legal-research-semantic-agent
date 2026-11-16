-- grain: one row per practice area, including PA00 Unspecified for firms with no survey.
select practice_area_id, practice_area
from {{ ref('practice_areas') }}
