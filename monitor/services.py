"""
DataPulse domain logic.
Connects to monitored PostgreSQL and evaluates rules.
Connection string comes from rule.connection (UI-managed) or
falls back to settings.MONITORED_DATABASE_URL.
"""

import psycopg2
from django.conf import settings
from django.utils import timezone

from .models import CheckRun, Rule, RuleResult


class MonitoredDbError(Exception):
    """Error connecting to the monitored database."""


def _get_connection(rule: Rule):
    """Open a connection to the monitored PostgreSQL for this rule."""
    if rule.connection_id:
        url = rule.connection.get_database_url()
        source = f'connection "{rule.connection.name}"'
    else:
        url = settings.MONITORED_DATABASE_URL
        source = 'MONITORED_DATABASE_URL'

    if not url:
        raise MonitoredDbError(
            f'No database URL configured. '
            f'Assign a Connection to this rule or set MONITORED_DATABASE_URL in environment.'
        )
    try:
        return psycopg2.connect(url)
    except psycopg2.OperationalError as e:
        raise MonitoredDbError(f'Cannot connect ({source}): {e}') from e


def _check_rule(conn, rule: Rule) -> dict:
    """Check one rule on an open connection."""
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
        if rule.connection_id:
            url = rule.connection.get_database_url()
        else:
            url = settings.MONITORED_DATABASE_URL

        if not url:
            result = RuleResult.objects.create(
                run=run, rule=rule,
                status=RuleResult.Status.ERROR,
                error_message='No database URL configured for this rule.',
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

    # Group rules by connection URL to reuse connections
    conn_cache: dict[str | None, tuple] = {}  # url -> (conn, error)

    for rule in rules:
        try:
            if rule.connection_id:
                url = rule.connection.get_database_url()
            else:
                url = settings.MONITORED_DATABASE_URL

            if url not in conn_cache:
                try:
                    conn_cache[url] = (psycopg2.connect(url) if url else None, None)
                except psycopg2.OperationalError as e:
                    conn_cache[url] = (None, str(e))

            conn, conn_error = conn_cache[url]

            if conn_error or conn is None:
                msg = conn_error or 'No database URL configured for this rule.'
                RuleResult.objects.create(
                    run=run, rule=rule,
                    status=RuleResult.Status.ERROR,
                    error_message=msg,
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
