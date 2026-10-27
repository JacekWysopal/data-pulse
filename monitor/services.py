"""
DataPulse domain logic.
Connects to monitored PostgreSQL and evaluates rules.
Connection string comes exclusively from rule.connection (UI-managed).
Rules without a Connection assigned will return ERROR status.
"""

import re

import psycopg2
from django.utils import timezone

from .models import CheckRun, Connection, Rule, RuleResult

SCHEMA_CACHE_TTL = 300  # 5 minutes


class MonitoredDbError(Exception):
    """Error connecting to the monitored database."""


def _open_conn(url: str):
    """Open a psycopg2 connection from a URL string."""
    if not url:
        raise MonitoredDbError('No database URL provided.')
    try:
        return psycopg2.connect(url)
    except psycopg2.OperationalError as e:
        raise MonitoredDbError(str(e)) from e


def get_schema_tables(conn_id: int) -> dict:
    """
    Return list of (schema, table) pairs from information_schema.
    Result: {'tables': [{'schema': ..., 'table': ...}, ...], 'error': None}
    """
    try:
        conn_obj = Connection.objects.get(pk=conn_id)
        url = conn_obj.get_database_url()
    except Connection.DoesNotExist:
        return {'tables': [], 'error': 'Connection not found.'}

    try:
        conn = _open_conn(url)
    except MonitoredDbError as e:
        return {'tables': [], 'error': str(e)}

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name
            """)
            rows = cur.fetchall()
        return {'tables': [{'schema': r[0], 'table': r[1]} for r in rows], 'error': None}
    except psycopg2.Error as e:
        return {'tables': [], 'error': str(e)}
    finally:
        conn.close()


def get_schema_columns(conn_id: int, schema: str, table: str) -> dict:
    """
    Return columns for a given schema.table.
    Result: {'columns': [{'name': ..., 'type': ..., 'is_timestamp': bool}, ...], 'error': None}
    """
    try:
        conn_obj = Connection.objects.get(pk=conn_id)
        url = conn_obj.get_database_url()
    except Connection.DoesNotExist:
        return {'columns': [], 'error': 'Connection not found.'}

    try:
        conn = _open_conn(url)
    except MonitoredDbError as e:
        return {'columns': [], 'error': str(e)}

    TIMESTAMP_TYPES = {
        'timestamp', 'timestamp without time zone', 'timestamp with time zone',
        'timestamptz', 'date', 'time', 'timetz',
    }

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table))
            rows = cur.fetchall()
        return {
            'columns': [
                {
                    'name': r[0],
                    'type': r[1],
                    'is_timestamp': r[1].lower() in TIMESTAMP_TYPES,
                }
                for r in rows
            ],
            'error': None,
        }
    except psycopg2.Error as e:
        return {'columns': [], 'error': str(e)}
    finally:
        conn.close()


def _check_rule(conn, rule: Rule) -> dict:
    """Dispatch to the correct check based on rule type."""
    if rule.rule_type == Rule.RuleType.CUSTOM_SQL:
        return _check_custom_sql(conn, rule)
    return _check_volume_freshness(conn, rule)


SQL_ALLOWED = re.compile(r'^\s*SELECT\b', re.IGNORECASE)
SQL_FORBIDDEN = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|EXECUTE|CALL)\b',
    re.IGNORECASE,
)


def _check_custom_sql(conn, rule: Rule) -> dict:
    """Execute custom SQL and interpret result as boolean."""
    result = {
        'row_count': None,
        'last_record_age_hours': None,
        'status': RuleResult.Status.OK,
        'error_message': '',
    }

    sql = (rule.custom_sql or '').strip()
    if not sql:
        result['status'] = RuleResult.Status.ERROR
        result['error_message'] = 'Custom SQL is empty.'
        return result

    if not SQL_ALLOWED.match(sql):
        result['status'] = RuleResult.Status.ERROR
        result['error_message'] = 'Custom SQL must start with SELECT.'
        return result

    if SQL_FORBIDDEN.search(sql):
        result['status'] = RuleResult.Status.ERROR
        result['error_message'] = 'Custom SQL contains forbidden keywords (INSERT/UPDATE/DROP etc.).'
        return result

    try:
        with conn.cursor() as cur:
            cur.execute('SET statement_timeout = 30000')  # 30s
            cur.execute(sql)
            row = cur.fetchone()

        if row is None:
            result['status'] = RuleResult.Status.FAIL
            return result

        val = row[0]
        falsy = {False, 0, '0', 'f', 'false', 'no', 'n', None}
        if isinstance(val, str):
            val_norm = val.strip().lower()
        else:
            val_norm = val

        if val_norm in falsy:
            result['status'] = RuleResult.Status.FAIL

    except psycopg2.Error as e:
        result['status'] = RuleResult.Status.ERROR
        result['error_message'] = str(e)

    return result


def _check_volume_freshness(conn, rule: Rule) -> dict:
    result = {
        'row_count': None,
        'last_record_age_hours': None,
        'status': RuleResult.Status.OK,
        'error_message': '',
    }

    try:
        with conn.cursor() as cur:
            table = f'"{rule.schema_name}"."{rule.table_name}"'

            if rule.min_row_count is not None:
                cur.execute(f'SELECT COUNT(*) FROM {table}')  # noqa: S608
                (count,) = cur.fetchone()
                result['row_count'] = count
                if count < rule.min_row_count:
                    result['status'] = RuleResult.Status.FAIL

            if rule.timestamp_column and rule.max_age_hours is not None:
                col = f'"{rule.timestamp_column}"'
                cur.execute(
                    f'SELECT EXTRACT(EPOCH FROM (NOW() - MAX({col}))) / 3600 FROM {table}'  # noqa: S608
                )
                (age_hours,) = cur.fetchone()
                result['last_record_age_hours'] = float(age_hours) if age_hours is not None else None

                if age_hours is None or age_hours > rule.max_age_hours:
                    result['status'] = RuleResult.Status.FAIL

    except psycopg2.Error as e:
        result['status'] = RuleResult.Status.ERROR
        result['error_message'] = str(e)

    return result


def run_single_rule(rule: Rule) -> RuleResult:
    """Run one rule and return its RuleResult (inside a fresh CheckRun)."""
    run = CheckRun.objects.create()
    try:
        if not rule.connection_id:
            result = RuleResult.objects.create(
                run=run, rule=rule,
                status=RuleResult.Status.ERROR,
                error_message='No connection assigned. Add a Connection in the Connections page and assign it to this rule.',
            )
        else:
            url = rule.connection.get_database_url()
            if not url:
                result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='Connection URL is empty. Edit the connection and provide a valid database URL.',
                )
            else:
                try:
                    conn = psycopg2.connect(url)
                    data = _check_rule(conn, rule)
                    conn.close()
                    result = RuleResult.objects.create(
                        run=run, rule=rule,
                        status=data['status'],
                        row_count=data['row_count'],
                        last_record_age_hours=data['last_record_age_hours'],
                        error_message=data['error_message'],
                    )
                except psycopg2.OperationalError as e:
                    result = RuleResult.objects.create(
                        run=run, rule=rule,
                        status=RuleResult.Status.ERROR,
                        error_message=str(e),
                    )
    except Exception as e:
        result = RuleResult.objects.create(
            run=run, rule=rule,
            status=RuleResult.Status.ERROR,
            error_message=str(e),
        )

    run.finished_at = timezone.now()
    run.save()
    return result


def run_all_checks() -> CheckRun:
    run = CheckRun.objects.create()
    rules = Rule.objects.select_related('connection').all()

    # Cache open connections by URL to avoid duplicate connections per run
    conn_cache: dict[str, tuple] = {}  # url -> (conn, error_msg)

    for rule in rules:
        try:
            if not rule.connection_id:
                RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='No connection assigned. Add a Connection and assign it to this rule.',
                )
                continue

            url = rule.connection.get_database_url()
            if not url:
                RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='Connection URL is empty.',
                )
                continue

            if url not in conn_cache:
                try:
                    conn_cache[url] = (psycopg2.connect(url), None)
                except psycopg2.OperationalError as e:
                    conn_cache[url] = (None, str(e))

            conn, conn_error = conn_cache[url]

            if conn_error or conn is None:
                RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message=conn_error or 'Connection failed.',
                )
            else:
                result = _check_rule(conn, rule)
                RuleResult.objects.create(
                    run=run, rule=rule,
                    status=result['status'],
                    row_count=result['row_count'],
                    last_record_age_hours=result['last_record_age_hours'],
                    error_message=result['error_message'],
                )

        except Exception as e:
            RuleResult.objects.create(
                run=run, rule=rule,
                status=RuleResult.Status.ERROR,
                error_message=str(e),
            )

    for conn, _ in conn_cache.values():
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    run.finished_at = timezone.now()
    run.save()
    return run
