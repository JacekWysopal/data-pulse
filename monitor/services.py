"""
Logika domenowa DataPulse.
Łączy się z monitorowaną bazą PostgreSQL i ocenia reguły.
Connection string pochodzi wyłącznie z settings.MONITORED_DATABASE_URL.
"""

import psycopg2
from django.conf import settings
from django.utils import timezone

from .models import CheckRun, Rule, RuleResult


class MonitoredDbError(Exception):
    """Błąd połączenia z monitorowaną bazą."""


def _get_connection():
    """Otwiera połączenie z monitorowaną bazą PostgreSQL."""
    url = settings.MONITORED_DATABASE_URL
    if not url:
        raise MonitoredDbError(
            'Brak MONITORED_DATABASE_URL w pliku .env. '
            'Uzupełnij connection string do monitorowanej bazy.'
        )
    try:
        return psycopg2.connect(url)
    except psycopg2.OperationalError as e:
        raise MonitoredDbError(f'Nie można połączyć się z bazą: {e}') from e


def _check_rule(conn, rule: Rule) -> dict:
    """
    Sprawdza jedną regułę na otwartym połączeniu.
    Zwraca słownik z row_count, last_record_age_hours, status, error_message.
    """
    result = {
        'row_count': None,
        'last_record_age_hours': None,
        'status': RuleResult.Status.OK,
        'error_message': '',
    }

    try:
        with conn.cursor() as cur:
            table = f'"{rule.schema_name}"."{rule.table_name}"'

            # Sprawdzenie wolumenu
            if rule.min_row_count is not None:
                cur.execute(f'SELECT COUNT(*) FROM {table}')  # noqa: S608
                (count,) = cur.fetchone()
                result['row_count'] = count
                if count < rule.min_row_count:
                    result['status'] = RuleResult.Status.FAIL

            # Sprawdzenie freshness
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


def run_all_checks() -> CheckRun:
    """
    Uruchamia sprawdzenie wszystkich reguł.
    Zawsze zwraca CheckRun — nawet gdy połączenie z bazą się nie uda,
    błąd jest rejestrowany per reguła zamiast przerywać cały przebieg.
    """
    run = CheckRun.objects.create()
    rules = Rule.objects.all()

    conn = None
    connection_error = None

    try:
        conn = _get_connection()
    except MonitoredDbError as e:
        connection_error = str(e)

    for rule in rules:
        if connection_error:
            RuleResult.objects.create(
                run=run,
                rule=rule,
                status=RuleResult.Status.ERROR,
                error_message=connection_error,
            )
        else:
            result = _check_rule(conn, rule)
            RuleResult.objects.create(
                run=run,
                rule=rule,
                status=result['status'],
                row_count=result['row_count'],
                last_record_age_hours=result['last_record_age_hours'],
                error_message=result['error_message'],
            )

    if conn:
        conn.close()

    run.finished_at = timezone.now()
    run.save()
    return run
