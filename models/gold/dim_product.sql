-- grain: one row per product. Hierarchy: product_line > product.
select product_id, product_name, product_line, is_core, cast(list_price_usd as decimal(18, 2)) as list_price_usd
from {{ ref('products') }}
