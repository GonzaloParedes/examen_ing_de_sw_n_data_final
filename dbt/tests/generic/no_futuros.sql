{% test no_futuros(model, column_name, ds) %}

select
    {{ column_name }}
from {{ model }}
where 
    {{ column_name }} is null
    or try_cast({{ column_name }} as date) is null
    or try_cast({{ column_name }} as date) > try_cast('{{ ds }}' as date)

{% endtest %}
