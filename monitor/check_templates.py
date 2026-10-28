"""
Built-in rule check templates.

TEMPLATES is the catalog of 8 pre-built SQL patterns. Each entry is a dict with:
  id          — slug used as the key in generate_sql()
  label       — short display name shown in the gallery card
  description — one-line human description
  params      — list of {name, label, placeholder} dicts; order matches the UI form
  sql         — dict keyed 'postgresql' / 'mysql', each a Python .format() string
                with named placeholders matching params[*].name

generate_sql(template_id, params, provider) renders the SQL string for the given
provider. Raises KeyError for an unknown template_id or provider.

Provider note (F1):
  pattern_match is the only template with provider-specific SQL.
  PostgreSQL uses !~ (regex does-not-match); MySQL uses NOT REGEXP.
  All other 7 templates produce identical SQL for both providers.

Referential integrity note (F2):
  referential_integrity requires all 4 params (child_table, child_column,
  parent_table, parent_column) to be non-empty. A missing param leaves a literal
  {placeholder} in the SQL, which causes a DB syntax error at execution time.
"""

TEMPLATES = [
    {
        "id": "null_check",
        "label": "Null check",
        "description": "No NULLs in column",
        "params": [
            {"name": "table",  "label": "Table",  "placeholder": "public.orders"},
            {"name": "column", "label": "Column", "placeholder": "customer_id"},
        ],
        "sql": {
            "postgresql": "SELECT COUNT(*) = 0 FROM {table} WHERE {column} IS NULL",
            "mysql":      "SELECT COUNT(*) = 0 FROM {table} WHERE {column} IS NULL",
        },
    },
    {
        "id": "uniqueness",
        "label": "Uniqueness",
        "description": "No duplicate values in column",
        "params": [
            {"name": "table",  "label": "Table",  "placeholder": "public.orders"},
            {"name": "column", "label": "Column", "placeholder": "order_id"},
        ],
        "sql": {
            "postgresql": "SELECT COUNT(*) = COUNT(DISTINCT {column}) FROM {table}",
            "mysql":      "SELECT COUNT(*) = COUNT(DISTINCT {column}) FROM {table}",
        },
    },
    {
        "id": "not_negative",
        "label": "Not negative",
        "description": "Numeric column has no negative values",
        "params": [
            {"name": "table",  "label": "Table",  "placeholder": "public.orders"},
            {"name": "column", "label": "Column", "placeholder": "amount"},
        ],
        "sql": {
            "postgresql": "SELECT MIN({column}) >= 0 FROM {table}",
            "mysql":      "SELECT MIN({column}) >= 0 FROM {table}",
        },
    },
    {
        "id": "future_date",
        "label": "No future date",
        "description": "Timestamp column does not exceed current time",
        "params": [
            {"name": "table",  "label": "Table",  "placeholder": "public.orders"},
            {"name": "column", "label": "Column", "placeholder": "created_at"},
        ],
        "sql": {
            "postgresql": "SELECT MAX({column}) <= NOW() FROM {table}",
            "mysql":      "SELECT MAX({column}) <= NOW() FROM {table}",
        },
    },
    {
        "id": "referential_integrity",
        "label": "Referential integrity",
        "description": "All FK values exist in parent table",
        "params": [
            {"name": "child_table",   "label": "Child table",   "placeholder": "public.orders"},
            {"name": "child_column",  "label": "Child column",  "placeholder": "customer_id"},
            {"name": "parent_table",  "label": "Parent table",  "placeholder": "public.customers"},
            {"name": "parent_column", "label": "Parent column", "placeholder": "id"},
        ],
        "sql": {
            "postgresql": (
                "SELECT COUNT(*) = 0 FROM {child_table} "
                "WHERE {child_column} NOT IN (SELECT {parent_column} FROM {parent_table})"
            ),
            "mysql": (
                "SELECT COUNT(*) = 0 FROM {child_table} "
                "WHERE {child_column} NOT IN (SELECT {parent_column} FROM {parent_table})"
            ),
        },
    },
    {
        "id": "completeness_rate",
        "label": "Completeness rate",
        "description": "% non-null values >= threshold",
        "params": [
            {"name": "table",     "label": "Table",     "placeholder": "public.orders"},
            {"name": "column",    "label": "Column",    "placeholder": "email"},
            {"name": "threshold", "label": "Threshold (%)", "placeholder": "95"},
        ],
        "sql": {
            "postgresql": (
                "SELECT ROUND(100.0 * COUNT({column}) / NULLIF(COUNT(*), 0), 2) >= {threshold} FROM {table}"
            ),
            "mysql": (
                "SELECT ROUND(100.0 * COUNT({column}) / NULLIF(COUNT(*), 0), 2) >= {threshold} FROM {table}"
            ),
        },
    },
    {
        "id": "row_count_equals",
        "label": "Row count equals",
        "description": "Table has exactly the expected number of rows",
        "params": [
            {"name": "table",          "label": "Table",          "placeholder": "public.orders"},
            {"name": "expected_count", "label": "Expected count", "placeholder": "1000"},
        ],
        "sql": {
            "postgresql": "SELECT COUNT(*) = {expected_count} FROM {table}",
            "mysql":      "SELECT COUNT(*) = {expected_count} FROM {table}",
        },
    },
    {
        "id": "pattern_match",
        "label": "Pattern match",
        "description": "Column values match a regex pattern",
        "params": [
            {"name": "table",   "label": "Table",   "placeholder": "public.orders"},
            {"name": "column",  "label": "Column",  "placeholder": "email"},
            {"name": "pattern", "label": "Pattern", "placeholder": "^[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}$"},
        ],
        "sql": {
            # PostgreSQL: !~ = "does not match regex"
            "postgresql": "SELECT COUNT(*) = 0 FROM {table} WHERE {column} !~ '{pattern}'",
            # MySQL: NOT REGEXP
            "mysql":      "SELECT COUNT(*) = 0 FROM {table} WHERE {column} NOT REGEXP '{pattern}'",
        },
    },
]

# Build a fast lookup dict for generate_sql
_TEMPLATE_INDEX = {t["id"]: t for t in TEMPLATES}


def generate_sql(template_id: str, params: dict, provider: str) -> str:
    """
    Render the SQL string for the given template_id, params mapping, and provider.

    Args:
        template_id: One of the 8 template ids (e.g. 'null_check').
        params:      Dict mapping param names to string values,
                     e.g. {'table': 'public.orders', 'column': 'email'}.
        provider:    'postgresql' or 'mysql'. Raises KeyError for unknown values.

    Returns:
        Rendered SELECT string ready to drop into Rule.custom_sql.

    Raises:
        KeyError: if template_id or provider is unknown.
    """
    template = _TEMPLATE_INDEX[template_id]   # KeyError on unknown template_id
    sql_pattern = template["sql"][provider]    # KeyError on unknown provider
    return sql_pattern.format(**params)
