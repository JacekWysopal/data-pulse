"""
DataPulse domain logic.
Connects to monitored PostgreSQL or MySQL databases and evaluates rules.
Connection string comes exclusively from rule.connection (UI-managed).
Rules without a Connection assigned will return ERROR status.
"""

import re
from urllib.parse import urlparse

import psycopg2
import pymysql
import pymysql.err
from django.utils import timezone

from .email_service import send_fail_notification
from .models import CheckRun, Connection, Rule, RuleResult

SCHEMA_CACHE_TTL = 300  # 5 minutes


class MonitoredDbError(Exception):
    """Error connecting to the monitored database."""


def _parse_mysql_url(url: str) -> dict:
    """Parse mysql[+pymysql]://user:pass@host:port/db into pymysql.connect() kwargs."""
    p = urlparse(url)
    return {
        'host': p.hostname,
        'port': p.port or 3306,
        'user': p.username,
        'password': p.password or '',
        'database': p.path.lstrip('/'),
        'autocommit': True,
    }


def _open_conn(url: str, provider: str = 'postgresql'):
    """Open a database connection from a URL string, dispatching by provider."""
    if not url:
        raise MonitoredDbError('No database URL provided.')
    try:
        if provider == 'mysql':
            kwargs = _parse_mysql_url(url)
            return pymysql.connect(**kwargs)
        else:
            return psycopg2.connect(url)
    except (psycopg2.OperationalError, pymysql.err.OperationalError) as e:
        raise MonitoredDbError(str(e)) from e


# MySQL system schemas to exclude from table introspection
_MYSQL_SYSTEM_SCHEMAS = ('information_schema', 'performance_schema', 'mysql', 'sys')

# Timestamp-like column types for both PostgreSQL and MySQL
TIMESTAMP_TYPES = {
    # PostgreSQL
    'timestamp', 'timestamp without time zone', 'timestamp with time zone',
    'timestamptz', 'date', 'time', 'timetz',
    # MySQL
    'datetime',
}


def get_schema_tables(conn_id: int) -> dict:
    """
    Return list of (schema, table) pairs from information_schema.
    Result: {'tables': [{'schema': ..., 'table': ...}, ...], 'error': None}
    """
    try:
        conn_obj = Connection.objects.get(pk=conn_id)
        url = conn_obj.get_database_url()
        provider = conn_obj.provider
    except Connection.DoesNotExist:
        return {'tables': [], 'error': 'Connection not found.'}

    try:
        conn = _open_conn(url, provider)
    except MonitoredDbError as e:
        return {'tables': [], 'error': str(e)}

    try:
        with conn.cursor() as cur:
            if provider == 'mysql':
                exclusions = ', '.join(f"'{s}'" for s in _MYSQL_SYSTEM_SCHEMAS)
                cur.execute(f"""
                    SELECT table_schema, table_name
                    FROM information_schema.tables
                    WHERE table_schema NOT IN ({exclusions})
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_schema, table_name
                """)  # noqa: S608
            else:
                cur.execute("""
                    SELECT table_schema, table_name
                    FROM information_schema.tables
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_schema, table_name
                """)
            rows = cur.fetchall()
        return {'tables': [{'schema': r[0], 'table': r[1]} for r in rows], 'error': None}
    except (psycopg2.Error, pymysql.err.Error) as e:
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
        provider = conn_obj.provider
    except Connection.DoesNotExist:
        return {'columns': [], 'error': 'Connection not found.'}

    try:
        conn = _open_conn(url, provider)
    except MonitoredDbError as e:
        return {'columns': [], 'error': str(e)}

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
    except (psycopg2.Error, pymysql.err.Error) as e:
        return {'columns': [], 'error': str(e)}
    finally:
        conn.close()


def _mysql_ansi_quotes_enabled(conn) -> bool:
    """Return True if the MySQL connection has ANSI_QUOTES in its sql_mode.

    When ANSI_QUOTES is active, double-quote characters act as identifier
    quotes rather than string-literal delimiters. DataPulse uses backtick
    quoting (see _check_volume_freshness) which works regardless of this
    mode, but callers can use this function to detect non-standard setups.
    """
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT @@sql_mode')
            (sql_mode,) = cur.fetchone()
            return 'ANSI_QUOTES' in (sql_mode or '').upper()
    except Exception:
        return False


def _check_rule(conn, rule: Rule, provider: str = 'postgresql') -> dict:
    """Dispatch to the correct check based on rule type."""
    if rule.rule_type == Rule.RuleType.CUSTOM_SQL:
        return _check_custom_sql(conn, rule, provider)
    return _check_volume_freshness(conn, rule, provider)


SQL_ALLOWED = re.compile(r'^\s*SELECT\b', re.IGNORECASE)
SQL_FORBIDDEN = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|EXECUTE|CALL)\b',
    re.IGNORECASE,
)


def _check_custom_sql(conn, rule: Rule, provider: str = 'postgresql') -> dict:
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
            timeout_sql = (
                "SET LOCAL statement_timeout='30s'"
                if provider == 'postgresql'
                else 'SET SESSION max_execution_time=30000'
            )
            cur.execute(timeout_sql)
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

    except (psycopg2.Error, pymysql.err.Error) as e:
        result['status'] = RuleResult.Status.ERROR
        result['error_message'] = str(e)

    return result


def _check_volume_freshness(conn, rule: Rule, provider: str = 'postgresql') -> dict:
    result = {
        'row_count': None,
        'last_record_age_hours': None,
        'status': RuleResult.Status.OK,
        'error_message': '',
    }

    # MySQL default sql_mode does NOT include ANSI_QUOTES, so double-quote
    # characters are string literals, not identifier quotes. Use backticks for
    # MySQL; keep ANSI double-quote style for PostgreSQL.
    q = '`' if provider == 'mysql' else '"'

    try:
        with conn.cursor() as cur:
            table = f'{q}{rule.schema_name}{q}.{q}{rule.table_name}{q}'

            if rule.min_row_count is not None:
                cur.execute(f'SELECT COUNT(*) FROM {table}')  # noqa: S608
                (count,) = cur.fetchone()
                result['row_count'] = count
                if count < rule.min_row_count:
                    result['status'] = RuleResult.Status.FAIL

            if rule.timestamp_column and rule.max_age_hours is not None:
                col = f'{q}{rule.timestamp_column}{q}'
                if provider == 'postgresql':
                    freshness_sql = (
                        f'SELECT EXTRACT(EPOCH FROM (NOW() - MAX({col}))) / 3600 FROM {table}'  # noqa: S608
                    )
                else:
                    freshness_sql = (
                        f'SELECT TIMESTAMPDIFF(SECOND, MAX({col}), NOW()) / 3600 FROM {table}'  # noqa: S608
                    )
                cur.execute(freshness_sql)
                (age_hours,) = cur.fetchone()
                result['last_record_age_hours'] = float(age_hours) if age_hours is not None else None

                if age_hours is None or age_hours > rule.max_age_hours:
                    result['status'] = RuleResult.Status.FAIL

    except (psycopg2.Error, pymysql.err.Error) as e:
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
            if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                send_fail_notification(rule, result)
        else:
            url = rule.connection.get_database_url()
            provider = rule.connection.provider
            if not url:
                result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='Connection URL is empty. Edit the connection and provide a valid database URL.',
                )
                if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    send_fail_notification(rule, result)
            else:
                try:
                    conn = _open_conn(url, provider)
                    data = _check_rule(conn, rule, provider)
                    conn.close()
                    result = RuleResult.objects.create(
                        run=run, rule=rule,
                        status=data['status'],
                        row_count=data['row_count'],
                        last_record_age_hours=data['last_record_age_hours'],
                        error_message=data['error_message'],
                    )
                    if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                        send_fail_notification(rule, result)
                except MonitoredDbError as e:
                    result = RuleResult.objects.create(
                        run=run, rule=rule,
                        status=RuleResult.Status.ERROR,
                        error_message=str(e),
                    )
                    if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                        send_fail_notification(rule, result)
    except Exception as e:
        result = RuleResult.objects.create(
            run=run, rule=rule,
            status=RuleResult.Status.ERROR,
            error_message=str(e),
        )
        if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
            send_fail_notification(rule, result)

    run.finished_at = timezone.now()
    run.save()
    return result


def run_checks_for_user(user) -> CheckRun:
    """Run all checks for rules owned by a specific user.

    Used by the UI-triggered run_checks view so that pressing 'Run Checks'
    only executes rules belonging to the logged-in user.  The cron management
    command (run_scheduled) continues to call run_all_checks() which is
    intentionally unscoped.
    """
    run = CheckRun.objects.create()
    rules = Rule.objects.filter(user=user).select_related('connection')

    conn_cache: dict[str, tuple] = {}

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
            provider = rule.connection.provider
            if not url:
                RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='Connection URL is empty.',
                )
                continue

            if url not in conn_cache:
                try:
                    conn_cache[url] = (_open_conn(url, provider), None, provider)
                except MonitoredDbError as e:
                    conn_cache[url] = (None, str(e), provider)

            conn, conn_error, provider = conn_cache[url]

            if conn_error or conn is None:
                RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message=conn_error or 'Connection failed.',
                )
            else:
                result = _check_rule(conn, rule, provider)
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=result['status'],
                    row_count=result['row_count'],
                    last_record_age_hours=result['last_record_age_hours'],
                    error_message=result['error_message'],
                )
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    send_fail_notification(rule, db_result)

        except Exception as e:
            RuleResult.objects.create(
                run=run, rule=rule,
                status=RuleResult.Status.ERROR,
                error_message=str(e),
            )

    for conn, conn_error, provider in conn_cache.values():
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    run.finished_at = timezone.now()
    run.save()
    return run


def run_all_checks() -> CheckRun:
    run = CheckRun.objects.create()
    rules = Rule.objects.select_related('connection').all()

    # Cache open connections by URL to avoid duplicate connections per run
    # Value: (conn, error_msg, provider)
    conn_cache: dict[str, tuple] = {}

    for rule in rules:
        try:
            if not rule.connection_id:
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='No connection assigned. Add a Connection and assign it to this rule.',
                )
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    send_fail_notification(rule, db_result)
                continue

            url = rule.connection.get_database_url()
            provider = rule.connection.provider
            if not url:
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='Connection URL is empty.',
                )
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    send_fail_notification(rule, db_result)
                continue

            if url not in conn_cache:
                try:
                    conn_cache[url] = (_open_conn(url, provider), None, provider)
                except MonitoredDbError as e:
                    conn_cache[url] = (None, str(e), provider)

            conn, conn_error, provider = conn_cache[url]

            if conn_error or conn is None:
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message=conn_error or 'Connection failed.',
                )
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    send_fail_notification(rule, db_result)
            else:
                result = _check_rule(conn, rule, provider)
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=result['status'],
                    row_count=result['row_count'],
                    last_record_age_hours=result['last_record_age_hours'],
                    error_message=result['error_message'],
                )
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    send_fail_notification(rule, db_result)

        except Exception as e:
            db_result = RuleResult.objects.create(
                run=run, rule=rule,
                status=RuleResult.Status.ERROR,
                error_message=str(e),
            )
            if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                send_fail_notification(rule, db_result)

    for conn, conn_error, provider in conn_cache.values():
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    run.finished_at = timezone.now()
    run.save()
    return run
