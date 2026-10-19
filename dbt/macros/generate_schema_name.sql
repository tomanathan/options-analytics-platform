{# Use the custom schema as given ("silver", "gold") instead of dbt's default "<target schema>_<custom>". #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ (custom_schema_name or target.schema) | trim }}
{%- endmacro %}
