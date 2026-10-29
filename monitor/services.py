"""
DataPulse domain logic.
Connects to monitored PostgreSQL or MySQL databases and evaluates rules.
Connection string comes exclusively from rule.connection (UI-managed).
Rules without a Connection assigned will return ERROR status.
"""

import datetime
import decimal
import re
import types
from urllib.parse import urlparse

import psycopg2
import pymysql
import pymysql.err
from django.db import models
from django.utils import timezone

from .email_service import notify_rule_result, send_digest_notification
from .models import CheckRun, Connection, Rule, RuleResult

SCHEMA_CACHE_TTL = 300  # 5 minutes


def _get_notification_mode(user) -> str:
    """Return 'immediate' or 'digest'; defaults to immediate on missing profile."""
    try:
        return user.profile.notification_mode
    except Exception:
        return 'immediate'


def _update_consecutive_fails(rule: Rule, result: RuleResult) -> None:
    """Increment consecutive_fails on FAIL/ERROR, reset to 0 on OK."""
    if result.status == RuleResult.Status.OK:
        Rule.objects.filter(pk=rule.pk).update(consecutive_fails=0)
        rule.consecutive_fails = 0
    elif result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
        Rule.objects.filter(pk=rule.pk).update(
            consecutive_fails=models.F('consecutive_fails') + 1
        )
        rule.refresh_from_db(fields=['consecutive_fails'])


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


def _serialize_row(description, row: tuple) -> dict:
    """Convert a DBAPI2 (description, row) pair to a JSON-serializable dict.

    psycopg2 and pymysql may return datetime, date, and Decimal objects which
    are not JSON-native. This helper converts them to strings so the result
    dict can be stored as JSONField content without a custom encoder.
    """
    result = {}
    for col_desc, val in zip(description, row):
        col_name = col_desc[0]
        if isinstance(val, datetime.datetime):
            result[col_name] = val.isoformat()
        elif isinstance(val, datetime.date):
            result[col_name] = val.isoformat()
        elif isinstance(val, decimal.Decimal):
            result[col_name] = str(val)
        else:
            result[col_name] = val
    return result


def _fetch_sample_rows(cur, sql: str, params=None, limit: int = 5) -> list | None:
    """Execute a sampling query and return up to `limit` serialized row dicts.

    Returns None on any exception so a sampling failure never converts a FAIL
    result to ERROR. Uses an already-open cursor passed by the caller.
    """
    try:
        cur.execute(sql, params)
        rows = cur.fetchmany(limit)
        return [_serialize_row(cur.description, row) for row in rows]
    except Exception:
        return None


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
        'sample_rows': None,
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
            # Sampling: re-run validated SQL on a new cursor to capture failing rows
            if provider is not None:
                with conn.cursor() as sample_cur:
                    sample_cur.execute(timeout_sql)
                    result['sample_rows'] = _fetch_sample_rows(sample_cur, sql)
            return result

        val = row[0]
        falsy = {False, 0, '0', 'f', 'false', 'no', 'n', None}
        if isinstance(val, str):
            val_norm = val.strip().lower()
        else:
            val_norm = val

        if val_norm in falsy:
            result['status'] = RuleResult.Status.FAIL
            # Sampling: re-run validated SQL on a new cursor to capture failing rows
            if provider is not None:
                with conn.cursor() as sample_cur:
                    sample_cur.execute(timeout_sql)
                    result['sample_rows'] = _fetch_sample_rows(sample_cur, sql)

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
        'sample_rows': None,
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

    # Sampling: only on FAIL and only when provider is known (guard: provider is not None)
    if result['status'] == RuleResult.Status.FAIL and provider is not None:
        table = f'{q}{rule.schema_name}{q}.{q}{rule.table_name}{q}'
        try:
            with conn.cursor() as sample_cur:
                if rule.timestamp_column and rule.max_age_hours is not None:
                    # Freshness FAIL: 5 most recent rows ordered by ts_col DESC
                    col = f'{q}{rule.timestamp_column}{q}'
                    sample_sql = f'SELECT * FROM {table} ORDER BY {col} DESC LIMIT 5'  # noqa: S608
                else:
                    # Volume FAIL: up to 5 arbitrary rows
                    sample_sql = f'SELECT * FROM {table} LIMIT 5'  # noqa: S608
                result['sample_rows'] = _fetch_sample_rows(sample_cur, sample_sql)
        except Exception:
            pass  # sampling failure must not propagate

    return result


def preview_rule(params: dict, user) -> dict:
    """Run rule logic against the given connection without persisting anything.

    params keys (all optional except connection_id):
        connection_id    int
        rule_type        str  ('volume_freshness' | 'custom_sql')
        schema_name      str
        table_name       str
        custom_sql       str
        min_row_count    int | None
        timestamp_column str
        max_age_hours    int | None

    Returns a dict:
        status                  str  (RuleResult.Status value)
        row_count               int | None
        last_record_age_hours   float | None
        error_message           str
        sample_rows             list | None   (at most 3 entries)
    """
    error_result = {
        'status': RuleResult.Status.ERROR,
        'row_count': None,
        'last_record_age_hours': None,
        'error_message': '',
        'sample_rows': None,
    }

    connection_id = params.get('connection_id')
    try:
        conn_obj = Connection.objects.get(pk=connection_id, user=user)
    except Connection.DoesNotExist:
        return {**error_result, 'error_message': 'Connection not found or access denied.'}

    url = conn_obj.get_database_url()
    if not url:
        return {**error_result, 'error_message': 'Connection URL is empty.'}

    provider = conn_obj.provider

    # Build a transient Rule-like namespace satisfying _check_rule's interface
    rule_ns = types.SimpleNamespace(
        rule_type=params.get('rule_type', Rule.RuleType.VOLUME_FRESHNESS),
        schema_name=params.get('schema_name', ''),
        table_name=params.get('table_name', ''),
        custom_sql=params.get('custom_sql', ''),
        min_row_count=params.get('min_row_count'),
        timestamp_column=params.get('timestamp_column', ''),
        max_age_hours=params.get('max_age_hours'),
    )

    try:
        conn = _open_conn(url, provider)
        result = _check_rule(conn, rule_ns, provider)
        conn.close()
    except MonitoredDbError as e:
        return {**error_result, 'error_message': str(e)}

    # Limit sample rows to 3 for the preview
    if result.get('sample_rows'):
        result['sample_rows'] = result['sample_rows'][:3]

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
            _update_consecutive_fails(rule, result)
            if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                notify_rule_result(rule, result)
        else:
            url = rule.connection.get_database_url()
            provider = rule.connection.provider
            if not url:
                result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='Connection URL is empty. Edit the connection and provide a valid database URL.',
                )
                _update_consecutive_fails(rule, result)
                if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    notify_rule_result(rule, result)
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
                        sample_rows=data.get('sample_rows'),
                    )
                    _update_consecutive_fails(rule, result)
                    if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                        notify_rule_result(rule, result)
                except MonitoredDbError as e:
                    result = RuleResult.objects.create(
                        run=run, rule=rule,
                        status=RuleResult.Status.ERROR,
                        error_message=str(e),
                    )
                    _update_consecutive_fails(rule, result)
                    if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                        notify_rule_result(rule, result)
    except Exception as e:
        result = RuleResult.objects.create(
            run=run, rule=rule,
            status=RuleResult.Status.ERROR,
            error_message=str(e),
        )
        _update_consecutive_fails(rule, result)
        if result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
            notify_rule_result(rule, result)

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
    mode = _get_notification_mode(user)
    failing_results = []

    conn_cache: dict[str, tuple] = {}

    for rule in rules:
        try:
            if not rule.connection_id:
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='No connection assigned. Add a Connection and assign it to this rule.',
                )
                _update_consecutive_fails(rule, db_result)
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    if mode == 'immediate':
                        notify_rule_result(rule, db_result)
                    elif rule.notify_on_fail and rule.severity != Rule.Severity.INFO:
                        failing_results.append(db_result)
                continue

            url = rule.connection.get_database_url()
            provider = rule.connection.provider
            if not url:
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='Connection URL is empty.',
                )
                _update_consecutive_fails(rule, db_result)
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    if mode == 'immediate':
                        notify_rule_result(rule, db_result)
                    elif rule.notify_on_fail and rule.severity != Rule.Severity.INFO:
                        failing_results.append(db_result)
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
                _update_consecutive_fails(rule, db_result)
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    if mode == 'immediate':
                        notify_rule_result(rule, db_result)
                    elif rule.notify_on_fail and rule.severity != Rule.Severity.INFO:
                        failing_results.append(db_result)
            else:
                result = _check_rule(conn, rule, provider)
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=result['status'],
                    row_count=result['row_count'],
                    last_record_age_hours=result['last_record_age_hours'],
                    error_message=result['error_message'],
                    sample_rows=result.get('sample_rows'),
                )
                _update_consecutive_fails(rule, db_result)
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    if mode == 'immediate':
                        notify_rule_result(rule, db_result)
                    elif rule.notify_on_fail and rule.severity != Rule.Severity.INFO:
                        failing_results.append(db_result)

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

    if mode == 'digest' and failing_results:
        send_digest_notification(run, failing_results, user)

    run.finished_at = timezone.now()
    run.save()
    return run


def run_all_checks() -> CheckRun:
    run = CheckRun.objects.create()
    # select_related('user') avoids N+1 when reading rule.user.profile
    rules = Rule.objects.select_related('connection', 'user').all()

    # Cache open connections by URL to avoid duplicate connections per run
    # Value: (conn, error_msg, provider)
    conn_cache: dict[str, tuple] = {}

    # Accumulate digest-mode users' failing results: {user_id: (user, [results])}
    digest_pending: dict[int, tuple] = {}

    for rule in rules:
        try:
            mode = _get_notification_mode(rule.user)

            if not rule.connection_id:
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='No connection assigned. Add a Connection and assign it to this rule.',
                )
                _update_consecutive_fails(rule, db_result)
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    if mode == 'immediate':
                        notify_rule_result(rule, db_result)
                    elif rule.notify_on_fail and rule.severity != Rule.Severity.INFO:
                        uid = rule.user_id
                        if uid not in digest_pending:
                            digest_pending[uid] = (rule.user, [])
                        digest_pending[uid][1].append(db_result)
                continue

            url = rule.connection.get_database_url()
            provider = rule.connection.provider
            if not url:
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message='Connection URL is empty.',
                )
                _update_consecutive_fails(rule, db_result)
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    if mode == 'immediate':
                        notify_rule_result(rule, db_result)
                    elif rule.notify_on_fail and rule.severity != Rule.Severity.INFO:
                        uid = rule.user_id
                        if uid not in digest_pending:
                            digest_pending[uid] = (rule.user, [])
                        digest_pending[uid][1].append(db_result)
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
                _update_consecutive_fails(rule, db_result)
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    if mode == 'immediate':
                        notify_rule_result(rule, db_result)
                    elif rule.notify_on_fail and rule.severity != Rule.Severity.INFO:
                        uid = rule.user_id
                        if uid not in digest_pending:
                            digest_pending[uid] = (rule.user, [])
                        digest_pending[uid][1].append(db_result)
            else:
                result = _check_rule(conn, rule, provider)
                db_result = RuleResult.objects.create(
                    run=run, rule=rule,
                    status=result['status'],
                    row_count=result['row_count'],
                    last_record_age_hours=result['last_record_age_hours'],
                    error_message=result['error_message'],
                    sample_rows=result.get('sample_rows'),
                )
                _update_consecutive_fails(rule, db_result)
                if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                    if mode == 'immediate':
                        notify_rule_result(rule, db_result)
                    elif rule.notify_on_fail and rule.severity != Rule.Severity.INFO:
                        uid = rule.user_id
                        if uid not in digest_pending:
                            digest_pending[uid] = (rule.user, [])
                        digest_pending[uid][1].append(db_result)

        except Exception as e:
            db_result = RuleResult.objects.create(
                run=run, rule=rule,
                status=RuleResult.Status.ERROR,
                error_message=str(e),
            )
            if db_result.status in (RuleResult.Status.FAIL, RuleResult.Status.ERROR):
                notify_rule_result(rule, db_result)

    for conn, conn_error, provider in conn_cache.values():
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    # Dispatch one digest per digest-mode user
    for user, failing_results in digest_pending.values():
        send_digest_notification(run, failing_results, user)

    run.finished_at = timezone.now()
    run.save()
    return run
