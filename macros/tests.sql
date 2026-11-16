{# Generic tests, written here so the project needs no packages. Each returns the offending rows. #}

{% test in_range(model, column_name, min_value=none, max_value=none) %}
select {{ column_name }} as out_of_range_value
from {{ model }}
where {{ column_name }} is not null
  and (false
    {% if min_value is not none %} or {{ column_name }} < {{ min_value }} {% endif %}
    {% if max_value is not none %} or {{ column_name }} > {{ max_value }} {% endif %})
{% endtest %}

{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{% test no_overlapping_intervals(model, partition_by, from_col, to_col) %}
-- intervals are [from, to); each must end on or before the next one starts, and never be empty
select *
from (
    select {{ partition_by }}, {{ from_col }}, {{ to_col }},
           lead({{ from_col }}) over (partition by {{ partition_by }} order by {{ from_col }}) as next_from
    from {{ model }}
) t
where {{ to_col }} <= {{ from_col }} or (next_from is not null and {{ to_col }} > next_from)
{% endtest %}

{% test exactly_one_current(model, key, flag='is_current') %}
select {{ key }}, sum(case when {{ flag }} then 1 else 0 end) as n_current
from {{ model }}
group by {{ key }}
having sum(case when {{ flag }} then 1 else 0 end) <> 1
{% endtest %}

{% test weights_sum_to_one(model, key, weight) %}
select {{ key }}, sum({{ weight }}) as total_weight
from {{ model }}
group by {{ key }}
having abs(sum({{ weight }}) - 1) > 0.0001
{% endtest %}

{% test expression_true(model, expression) %}
select * from {{ model }} where not ({{ expression }})
{% endtest %}

{% test covers_every_key(model, column_name, to, field) %}
-- every key in `to` must appear in this model (the reverse of relationships)
select t.{{ field }}
from {{ to }} t
left join {{ model }} m on m.{{ column_name }} = t.{{ field }}
where m.{{ column_name }} is null
{% endtest %}
