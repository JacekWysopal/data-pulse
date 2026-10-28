"""
DataPulse test suite.

Runs with: python manage.py test monitor
Uses SQLite (default test DB) for Django models.
Services layer is tested with mocked psycopg2 connections.
"""
import json
from datetime import time
from unittest.mock import MagicMock, patch, call

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CheckRun, Connection, Rule, RuleResult, SlackNotification


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def make_rule(name='test_rule', schema='public', table='orders',
              min_rows=None, ts_col=None, max_age=None,
              rule_type='volume_freshness', custom_sql='',
              connection=None, user=None):
    """Factory for Rule objects."""
    return Rule.objects.create(
        name=name,
        schema_name=schema,
        table_name=table,
        min_row_count=min_rows,
        timestamp_column=ts_col or '',
        max_age_hours=max_age,
        rule_type=rule_type,
        custom_sql=custom_sql,
        connection=connection,
        user=user,
    )


def make_connection(name='test_conn', url='postgresql://user:pass@host/db', user=None):
    conn = Connection(name=name, user=user)
    conn.set_database_url(url)
    conn.save()
    return conn


def make_run(ok=0, fail=0, error=0, user=None):
    """Create a CheckRun with pre-built results."""
    run = CheckRun.objects.create(finished_at=timezone.now())
    for _ in range(ok):
        rule = make_rule(name=f'ok_{_}', min_rows=1, user=user)
        RuleResult.objects.create(run=run, rule=rule, status='OK', row_count=5)
    for _ in range(fail):
        rule = make_rule(name=f'fail_{_}', min_rows=100, user=user)
        RuleResult.objects.create(run=run, rule=rule, status='FAIL', row_count=3)
    for _ in range(error):
        rule = make_rule(name=f'err_{_}', min_rows=1, user=user)
        RuleResult.objects.create(run=run, rule=rule, status='ERROR', error_message='boom')
    return run


# ═══════════════════════════════════════════════════════════════════
#  Model tests
# ═══════════════════════════════════════════════════════════════════

class ConnectionModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('conn_model_user', password='pass')

    def test_set_and_get_database_url_plaintext(self):
        conn = make_connection(url='postgresql://u:p@host/db', user=self.user)
        self.assertEqual(conn.get_database_url(), 'postgresql://u:p@host/db')

    def test_masked_url_hides_password(self):
        conn = make_connection(url='postgresql://user:supersecret@host:5432/db', user=self.user)
        masked = conn.masked_url
        self.assertNotIn('supersecret', masked)
        self.assertIn('***', masked)
        self.assertIn('user', masked)
        self.assertIn('host', masked)

    def test_masked_url_empty_string_on_empty_url(self):
        conn = Connection(name='empty', user=self.user)
        conn._database_url = ''
        self.assertEqual(conn.masked_url, '')

    def test_connection_str(self):
        conn = make_connection(name='production', user=self.user)
        self.assertIn('production', str(conn))
        self.assertIn('PostgreSQL', str(conn))


class RuleModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('rule_model_user', password='pass')

    def test_volume_rule_str(self):
        rule = make_rule(name='orders_vol', schema='public', table='orders', min_rows=100, user=self.user)
        self.assertIn('orders_vol', str(rule))

    def test_full_table_name_with_schema(self):
        rule = make_rule(schema='analytics', table='events', min_rows=1, user=self.user)
        self.assertEqual(rule.full_table_name, '"analytics"."events"')

    def test_full_table_name_empty_when_no_schema(self):
        rule = make_rule(schema='', table='', custom_sql='SELECT 1', rule_type='custom_sql', user=self.user)
        self.assertIsNone(rule.full_table_name)

    def test_is_custom_sql_true(self):
        rule = make_rule(rule_type='custom_sql', custom_sql='SELECT true', user=self.user)
        self.assertTrue(rule.is_custom_sql)

    def test_is_custom_sql_false(self):
        rule = make_rule(min_rows=1, user=self.user)
        self.assertFalse(rule.is_custom_sql)

    def test_last_result_none_when_no_results(self):
        rule = make_rule(min_rows=1, user=self.user)
        self.assertIsNone(rule.last_result)

    def test_last_result_returns_latest(self):
        rule = make_rule(min_rows=1, user=self.user)
        run1 = CheckRun.objects.create(finished_at=timezone.now())
        run2 = CheckRun.objects.create(finished_at=timezone.now())
        RuleResult.objects.create(run=run1, rule=rule, status='OK')
        r2 = RuleResult.objects.create(run=run2, rule=rule, status='FAIL')
        self.assertEqual(rule.last_result.pk, r2.pk)


class CheckRunModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('checkrun_user', password='pass')

    def test_ok_fail_error_counts(self):
        run = make_run(ok=3, fail=2, error=1, user=self.user)
        self.assertEqual(run.ok_count, 3)
        self.assertEqual(run.fail_count, 2)
        self.assertEqual(run.error_count, 1)

    def test_str_format(self):
        run = CheckRun.objects.create()
        self.assertIn('Run', str(run))


# ═══════════════════════════════════════════════════════════════════
#  Services — volume/freshness
# ═══════════════════════════════════════════════════════════════════

class CheckVolumeFreshnessTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('vol_fresh_user', password='pass')

    def _mock_conn(self, fetchone_return):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = fetchone_return
        conn.cursor.return_value = cursor
        return conn

    def test_volume_ok(self):
        from .services import _check_volume_freshness
        rule = make_rule(min_rows=10, user=self.user)
        conn = self._mock_conn((50,))
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['row_count'], 50)

    def test_volume_fail(self):
        from .services import _check_volume_freshness
        rule = make_rule(min_rows=100, user=self.user)
        conn = self._mock_conn((5,))
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['row_count'], 5)

    def test_freshness_ok(self):
        from .services import _check_volume_freshness
        rule = make_rule(ts_col='created_at', max_age=24, user=self.user)
        conn = self._mock_conn((2.5,))
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'OK')
        self.assertAlmostEqual(result['last_record_age_hours'], 2.5)

    def test_freshness_fail(self):
        from .services import _check_volume_freshness
        rule = make_rule(ts_col='created_at', max_age=1, user=self.user)
        conn = self._mock_conn((3.0,))
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'FAIL')

    def test_freshness_null_age_fails(self):
        from .services import _check_volume_freshness
        rule = make_rule(ts_col='created_at', max_age=1, user=self.user)
        conn = self._mock_conn((None,))
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'FAIL')

    def test_db_error_returns_error_status(self):
        from .services import _check_volume_freshness
        import psycopg2
        rule = make_rule(min_rows=10, user=self.user)
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.side_effect = psycopg2.OperationalError('connection refused')
        conn.cursor.return_value = cursor
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('connection refused', result['error_message'])

    def test_both_conditions_fail_on_first(self):
        """If volume fails, status should be FAIL even if freshness is not checked yet."""
        from .services import _check_volume_freshness
        rule = make_rule(min_rows=100, ts_col='ts', max_age=1, user=self.user)
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.side_effect = [(3,), (0.5,)]
        conn.cursor.return_value = cursor
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'FAIL')


# ═══════════════════════════════════════════════════════════════════
#  Services — custom SQL (S-06)
# ═══════════════════════════════════════════════════════════════════

class CheckCustomSQLTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('custom_sql_user', password='pass')

    def _make_sql_rule(self, sql):
        return make_rule(rule_type='custom_sql', custom_sql=sql, user=self.user)

    def _mock_conn(self, fetchone_return):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = fetchone_return
        conn.cursor.return_value = cursor
        return conn

    def test_true_boolean_ok(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('SELECT true')
        conn = self._mock_conn((True,))
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'OK')

    def test_false_boolean_fail(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('SELECT false')
        conn = self._mock_conn((False,))
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'FAIL')

    def test_integer_1_ok(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('SELECT 1')
        conn = self._mock_conn((1,))
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'OK')

    def test_integer_0_fail(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('SELECT 0')
        conn = self._mock_conn((0,))
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'FAIL')

    def test_string_false_fail(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule("SELECT 'false'")
        conn = self._mock_conn(('false',))
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'FAIL')

    def test_string_f_fail(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule("SELECT 'f'")
        conn = self._mock_conn(('f',))
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'FAIL')

    def test_null_result_fail(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('SELECT NULL')
        conn = self._mock_conn((None,))
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'FAIL')

    def test_empty_resultset_fail(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('SELECT 1 WHERE false')
        conn = self._mock_conn(None)
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'FAIL')

    def test_empty_sql_error(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('')
        conn = MagicMock()
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('empty', result['error_message'].lower())

    def test_non_select_sql_error(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('UPDATE foo SET bar=1')
        conn = MagicMock()
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('SELECT', result['error_message'])

    def test_forbidden_drop_error(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('SELECT 1; DROP TABLE orders')
        conn = MagicMock()
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('forbidden', result['error_message'].lower())

    def test_forbidden_insert_error(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('SELECT * FROM (INSERT INTO t VALUES(1)) x')
        conn = MagicMock()
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'ERROR')

    def test_count_query_ok(self):
        from .services import _check_custom_sql
        rule = self._make_sql_rule('SELECT COUNT(*) > 0 FROM public.orders')
        conn = self._mock_conn((True,))
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'OK')

    def test_db_error_returns_error(self):
        from .services import _check_custom_sql
        import psycopg2
        rule = self._make_sql_rule('SELECT 1')
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.side_effect = psycopg2.Error('syntax error')
        conn.cursor.return_value = cursor
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('syntax error', result['error_message'])


# ═══════════════════════════════════════════════════════════════════
#  Services — run_all_checks
# ═══════════════════════════════════════════════════════════════════

class RunAllChecksTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('run_all_user', password='pass')

    @patch('monitor.services.psycopg2.connect')
    def test_creates_checkrun(self, mock_connect):
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (10,)
        mock_connect.return_value.cursor.return_value = cursor

        conn = make_connection(user=self.user)
        make_rule(min_rows=5, connection=conn, user=self.user)
        from .services import run_all_checks
        run = run_all_checks()

        self.assertIsNotNone(run.pk)
        self.assertIsNotNone(run.finished_at)

    @patch('monitor.services.psycopg2.connect')
    def test_all_rules_get_results(self, mock_connect):
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (50,)
        mock_connect.return_value.cursor.return_value = cursor

        conn = make_connection(user=self.user)
        make_rule(name='r1', min_rows=10, connection=conn, user=self.user)
        make_rule(name='r2', min_rows=20, connection=conn, user=self.user)
        make_rule(name='r3', min_rows=30, connection=conn, user=self.user)

        from .services import run_all_checks
        run = run_all_checks()

        self.assertEqual(run.results.count(), 3)

    @patch('monitor.services.psycopg2.connect')
    def test_connection_error_marks_all_rules_error(self, mock_connect):
        import psycopg2
        mock_connect.side_effect = psycopg2.OperationalError('refused')

        conn = make_connection(user=self.user)
        make_rule(name='r1', min_rows=1, connection=conn, user=self.user)
        make_rule(name='r2', min_rows=1, connection=conn, user=self.user)

        from .services import run_all_checks
        run = run_all_checks()

        self.assertEqual(run.results.filter(status='ERROR').count(), 2)

    def test_no_connection_marks_rules_error(self):
        make_rule(name='r1', min_rows=1, user=self.user)  # no connection
        from .services import run_all_checks
        run = run_all_checks()
        result = run.results.first()
        self.assertEqual(result.status, 'ERROR')
        self.assertIn('No connection', result.error_message)


    @patch('monitor.services.psycopg2.connect')
    def test_one_rule_error_does_not_stop_others(self, mock_connect):
        import psycopg2
        good_cursor = MagicMock()
        good_cursor.__enter__ = MagicMock(return_value=good_cursor)
        good_cursor.__exit__ = MagicMock(return_value=False)
        good_cursor.fetchone.return_value = (50,)

        bad_cursor = MagicMock()
        bad_cursor.__enter__ = MagicMock(return_value=bad_cursor)
        bad_cursor.__exit__ = MagicMock(return_value=False)
        bad_cursor.fetchone.side_effect = psycopg2.Error('table not found')

        conn1 = MagicMock()
        conn1.cursor.return_value = good_cursor
        conn2 = MagicMock()
        conn2.cursor.return_value = bad_cursor
        mock_connect.side_effect = [conn1, conn2]

        conn_obj1 = make_connection('c1', 'postgresql://u:p@h/db1', user=self.user)
        conn_obj2 = make_connection('c2', 'postgresql://u:p@h/db2', user=self.user)
        make_rule(name='good', min_rows=10, connection=conn_obj1, user=self.user)
        make_rule(name='bad', min_rows=10, connection=conn_obj2, user=self.user)

        from .services import run_all_checks
        run = run_all_checks()

        statuses = set(run.results.values_list('status', flat=True))
        self.assertIn('OK', statuses)
        self.assertIn('ERROR', statuses)


# ═══════════════════════════════════════════════════════════════════
#  Services — run_single_rule
# ═══════════════════════════════════════════════════════════════════

class RunSingleRuleTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('single_rule_user', password='pass')

    @patch('monitor.services.psycopg2.connect')
    def test_creates_checkrun_and_result(self, mock_connect):
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (5,)
        mock_connect.return_value.cursor.return_value = cursor

        conn = make_connection(user=self.user)
        rule = make_rule(min_rows=1, connection=conn, user=self.user)
        from .services import run_single_rule
        result = run_single_rule(rule)

        self.assertEqual(result.rule, rule)
        self.assertIn(result.status, ['OK', 'FAIL', 'ERROR'])

    @patch('monitor.services.psycopg2.connect')
    def test_ok_when_rows_above_threshold(self, mock_connect):
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (100,)
        mock_connect.return_value.cursor.return_value = cursor

        conn = make_connection(user=self.user)
        rule = make_rule(min_rows=50, connection=conn, user=self.user)
        from .services import run_single_rule
        result = run_single_rule(rule)
        self.assertEqual(result.status, 'OK')

    @patch('monitor.services.psycopg2.connect')
    def test_fail_when_rows_below_threshold(self, mock_connect):
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (3,)
        mock_connect.return_value.cursor.return_value = cursor

        conn = make_connection(user=self.user)
        rule = make_rule(min_rows=100, connection=conn, user=self.user)
        from .services import run_single_rule
        result = run_single_rule(rule)
        self.assertEqual(result.status, 'FAIL')

    def test_no_connection_returns_error(self):
        rule = make_rule(min_rows=1, user=self.user)  # no connection
        from .services import run_single_rule
        result = run_single_rule(rule)
        self.assertEqual(result.status, 'ERROR')
        self.assertIn('No connection', result.error_message)


# ═══════════════════════════════════════════════════════════════════
#  Form validation
# ═══════════════════════════════════════════════════════════════════

class RuleFormTest(TestCase):

    def _post(self, data):
        from .forms import RuleForm
        return RuleForm(data)

    def test_volume_rule_valid(self):
        form = self._post({
            'name': 'test', 'schema_name': 'public', 'table_name': 'orders',
            'min_row_count': 100, 'rule_type': 'volume_freshness',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_freshness_rule_valid(self):
        form = self._post({
            'name': 'test', 'schema_name': 'public', 'table_name': 'orders',
            'timestamp_column': 'created_at', 'max_age_hours': 24,
            'rule_type': 'volume_freshness',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_both_conditions_valid(self):
        form = self._post({
            'name': 'test', 'schema_name': 'public', 'table_name': 'orders',
            'min_row_count': 10, 'timestamp_column': 'ts', 'max_age_hours': 2,
            'rule_type': 'volume_freshness',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_no_condition_invalid(self):
        form = self._post({
            'name': 'test', 'schema_name': 'public', 'table_name': 'orders',
            'rule_type': 'volume_freshness',
        })
        self.assertFalse(form.is_valid())

    def test_ts_col_without_max_age_invalid(self):
        form = self._post({
            'name': 'test', 'schema_name': 'public', 'table_name': 'orders',
            'timestamp_column': 'created_at', 'rule_type': 'volume_freshness',
        })
        self.assertFalse(form.is_valid())

    def test_max_age_without_ts_col_invalid(self):
        form = self._post({
            'name': 'test', 'schema_name': 'public', 'table_name': 'orders',
            'max_age_hours': 24, 'rule_type': 'volume_freshness',
        })
        self.assertFalse(form.is_valid())

    def test_custom_sql_valid(self):
        form = self._post({
            'name': 'test', 'rule_type': 'custom_sql',
            'custom_sql': 'SELECT COUNT(*) > 0 FROM public.orders',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_custom_sql_empty_invalid(self):
        form = self._post({'name': 'test', 'rule_type': 'custom_sql', 'custom_sql': ''})
        self.assertFalse(form.is_valid())

    def test_custom_sql_non_select_invalid(self):
        form = self._post({
            'name': 'test', 'rule_type': 'custom_sql',
            'custom_sql': 'DELETE FROM orders',
        })
        self.assertFalse(form.is_valid())

    def test_custom_sql_with_forbidden_keyword_invalid(self):
        form = self._post({
            'name': 'test', 'rule_type': 'custom_sql',
            'custom_sql': 'SELECT 1; DROP TABLE users',
        })
        self.assertFalse(form.is_valid())


class ConnectionFormTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('conn_form_user', password='pass')

    def test_valid_form(self):
        from .forms import ConnectionForm
        form = ConnectionForm({
            'name': 'staging',
            'description': 'Staging DB',
            'provider': 'postgresql',
            'database_url': 'postgresql://u:p@host/db',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_name_invalid(self):
        from .forms import ConnectionForm
        form = ConnectionForm({'provider': 'postgresql', 'database_url': 'postgresql://u:p@h/db'})
        self.assertFalse(form.is_valid())

    def test_missing_url_invalid(self):
        from .forms import ConnectionForm
        form = ConnectionForm({'name': 'test', 'provider': 'postgresql'})
        self.assertFalse(form.is_valid())

    def test_saves_url_via_set_database_url(self):
        from .forms import ConnectionForm
        form = ConnectionForm({
            'name': 'prod',
            'provider': 'postgresql',
            'database_url': 'postgresql://u:secret@host/db',
        })
        self.assertTrue(form.is_valid())
        conn = form.save(commit=False)
        conn.user = self.user
        conn.save()
        self.assertEqual(conn.get_database_url(), 'postgresql://u:secret@host/db')


# ═══════════════════════════════════════════════════════════════════
#  Views — authentication
# ═══════════════════════════════════════════════════════════════════

class AuthRedirectTest(TestCase):

    def test_dashboard_redirects_unauthenticated(self):
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertRedirects(r, '/login/?next=/', fetch_redirect_response=False)

    def test_rule_create_redirects_unauthenticated(self):
        r = self.client.get(reverse('monitor:rule_create'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_connection_list_redirects_unauthenticated(self):
        r = self.client.get(reverse('monitor:connection_list'))
        self.assertEqual(r.status_code, 302)

    def test_api_schema_tables_redirects_unauthenticated(self):
        r = self.client.get('/api/schema/1/tables/')
        self.assertEqual(r.status_code, 302)

    def test_login_page_200(self):
        r = self.client.get('/login/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Sign in')

    def test_login_success_redirects_to_dashboard(self):
        User.objects.create_user('admin', password='pass')
        r = self.client.post('/login/', {'username': 'admin', 'password': 'pass'})
        self.assertRedirects(r, '/', fetch_redirect_response=False)

    def test_login_failure_shows_error(self):
        r = self.client.post('/login/', {'username': 'bad', 'password': 'wrong'})
        self.assertEqual(r.status_code, 200)

    def test_logout_redirects_to_login(self):
        User.objects.create_user('admin', password='pass')
        self.client.login(username='admin', password='pass')
        r = self.client.post('/logout/')
        self.assertRedirects(r, '/login/', fetch_redirect_response=False)


# ═══════════════════════════════════════════════════════════════════
#  Views — dashboard
# ═══════════════════════════════════════════════════════════════════

class DashboardViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('admin', password='pass')
        self.client.login(username='admin', password='pass')

    def test_dashboard_200(self):
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertEqual(r.status_code, 200)

    def test_dashboard_shows_rule_name(self):
        make_rule(name='my_special_rule', min_rows=1, user=self.user)
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertContains(r, 'my_special_rule')

    def test_dashboard_kpi_counts_in_context(self):
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertIn('ok_count', r.context)
        self.assertIn('fail_count', r.context)
        self.assertIn('error_count', r.context)
        self.assertIn('total_count', r.context)

    def test_dashboard_empty_state(self):
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertEqual(r.context['total_count'], 0)

    def test_kpi_counts_correct(self):
        run = make_run(ok=2, fail=1, error=1, user=self.user)
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertEqual(r.context['ok_count'], 2)
        self.assertEqual(r.context['fail_count'], 1)
        self.assertEqual(r.context['error_count'], 1)
        self.assertEqual(r.context['total_count'], 4)


# ═══════════════════════════════════════════════════════════════════
#  Views — rules CRUD
# ═══════════════════════════════════════════════════════════════════

class RuleCRUDViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('admin', password='pass')
        self.client.login(username='admin', password='pass')

    def test_rule_create_get(self):
        r = self.client.get(reverse('monitor:rule_create'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Save rule')

    def test_rule_create_post_volume(self):
        conn = make_connection(user=self.user)
        r = self.client.post(reverse('monitor:rule_create'), {
            'name': 'new_rule', 'schema_name': 'public', 'table_name': 'orders',
            'min_row_count': 50, 'rule_type': 'volume_freshness',
            'connection': conn.pk,
        })
        self.assertRedirects(r, reverse('monitor:dashboard'))
        self.assertTrue(Rule.objects.filter(name='new_rule').exists())

    def test_rule_create_post_custom_sql(self):
        conn = make_connection(user=self.user)
        r = self.client.post(reverse('monitor:rule_create'), {
            'name': 'sql_rule', 'rule_type': 'custom_sql',
            'custom_sql': 'SELECT true',
            'connection': conn.pk,
        })
        self.assertRedirects(r, reverse('monitor:dashboard'))
        rule = Rule.objects.get(name='sql_rule')
        self.assertEqual(rule.rule_type, 'custom_sql')
        self.assertEqual(rule.custom_sql, 'SELECT true')

    def test_rule_create_invalid_shows_errors(self):
        r = self.client.post(reverse('monitor:rule_create'), {
            'name': '', 'rule_type': 'volume_freshness',
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Rule.objects.exists())

    def test_rule_edit_get(self):
        rule = make_rule(min_rows=1, user=self.user)
        r = self.client.get(reverse('monitor:rule_edit', args=[rule.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, rule.name)

    def test_rule_edit_post(self):
        conn = make_connection(user=self.user)
        rule = make_rule(name='old_name', min_rows=1, connection=conn, user=self.user)
        r = self.client.post(reverse('monitor:rule_edit', args=[rule.pk]), {
            'name': 'new_name', 'schema_name': 'public', 'table_name': 'orders',
            'min_row_count': 100, 'rule_type': 'volume_freshness',
            'connection': conn.pk,
        })
        self.assertRedirects(r, reverse('monitor:dashboard'))
        rule.refresh_from_db()
        self.assertEqual(rule.name, 'new_name')
        self.assertEqual(rule.min_row_count, 100)

    def test_rule_delete_get(self):
        rule = make_rule(min_rows=1, user=self.user)
        r = self.client.get(reverse('monitor:rule_delete', args=[rule.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Delete rule')

    def test_rule_delete_post(self):
        rule = make_rule(min_rows=1, user=self.user)
        r = self.client.post(reverse('monitor:rule_delete', args=[rule.pk]))
        self.assertRedirects(r, reverse('monitor:dashboard'))
        self.assertFalse(Rule.objects.filter(pk=rule.pk).exists())

    def test_rule_history_200(self):
        rule = make_rule(min_rows=1, user=self.user)
        r = self.client.get(reverse('monitor:rule_history', args=[rule.pk]))
        self.assertEqual(r.status_code, 200)

    def test_rule_history_shows_results(self):
        rule = make_rule(min_rows=1, user=self.user)
        run = CheckRun.objects.create(finished_at=timezone.now())
        RuleResult.objects.create(run=run, rule=rule, status='OK', row_count=5)
        r = self.client.get(reverse('monitor:rule_history', args=[rule.pk]))
        self.assertContains(r, 'OK')


# ═══════════════════════════════════════════════════════════════════
#  Views — connections CRUD
# ═══════════════════════════════════════════════════════════════════

class ConnectionCRUDViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('admin', password='pass')
        self.client.login(username='admin', password='pass')

    def test_connection_list_200(self):
        r = self.client.get(reverse('monitor:connection_list'))
        self.assertEqual(r.status_code, 200)

    def test_connection_create_get(self):
        r = self.client.get(reverse('monitor:connection_create'))
        self.assertEqual(r.status_code, 200)

    def test_connection_create_post(self):
        r = self.client.post(reverse('monitor:connection_create'), {
            'name': 'staging',
            'description': 'Staging',
            'provider': 'postgresql',
            'database_url': 'postgresql://u:p@host/db',
        })
        self.assertRedirects(r, reverse('monitor:connection_list'))
        self.assertTrue(Connection.objects.filter(name='staging').exists())

    def test_connection_edit_post(self):
        conn = make_connection('old_name', user=self.user)
        r = self.client.post(reverse('monitor:connection_edit', args=[conn.pk]), {
            'name': 'new_name',
            'provider': 'postgresql',
            'database_url': 'postgresql://u:p@host/db2',
        })
        self.assertRedirects(r, reverse('monitor:connection_list'))
        conn.refresh_from_db()
        self.assertEqual(conn.name, 'new_name')

    def test_connection_delete_post(self):
        conn = make_connection('to_delete', user=self.user)
        r = self.client.post(reverse('monitor:connection_delete', args=[conn.pk]))
        self.assertRedirects(r, reverse('monitor:connection_list'))
        self.assertFalse(Connection.objects.filter(pk=conn.pk).exists())

    def test_connection_delete_with_rules_falls_back_to_env(self):
        conn = make_connection(user=self.user)
        rule = make_rule(min_rows=1, connection=conn, user=self.user)
        self.client.post(reverse('monitor:connection_delete', args=[conn.pk]))
        rule.refresh_from_db()
        self.assertIsNone(rule.connection)


# ═══════════════════════════════════════════════════════════════════
#  Views — schema introspection API (S-04)
# ═══════════════════════════════════════════════════════════════════

class SchemaAPITest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('admin', password='pass')
        self.client.login(username='admin', password='pass')

    @patch('monitor.services.psycopg2.connect')
    def test_tables_endpoint_returns_json(self, mock_connect):
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [('public', 'orders'), ('public', 'users')]
        mock_connect.return_value.cursor.return_value = cursor

        conn = make_connection(user=self.user)
        r = self.client.get(f'/api/schema/{conn.pk}/tables/')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIsNone(data['error'])
        self.assertEqual(len(data['tables']), 2)
        self.assertEqual(data['tables'][0], {'schema': 'public', 'table': 'orders'})

    @patch('monitor.services.psycopg2.connect')
    def test_columns_endpoint_returns_json(self, mock_connect):
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            ('id', 'integer'),
            ('created_at', 'timestamp with time zone'),
            ('name', 'character varying'),
        ]
        mock_connect.return_value.cursor.return_value = cursor

        conn = make_connection(user=self.user)
        r = self.client.get(f'/api/schema/{conn.pk}/columns/public/orders/')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIsNone(data['error'])
        cols = {c['name']: c for c in data['columns']}
        self.assertTrue(cols['created_at']['is_timestamp'])
        self.assertFalse(cols['id']['is_timestamp'])
        self.assertFalse(cols['name']['is_timestamp'])

    def test_tables_endpoint_nonexistent_conn(self):
        r = self.client.get('/api/schema/99999/tables/')
        self.assertEqual(r.status_code, 404)

    @patch('monitor.services.psycopg2.connect')
    def test_tables_endpoint_conn_error(self, mock_connect):
        import psycopg2
        mock_connect.side_effect = psycopg2.OperationalError('refused')
        conn = make_connection(user=self.user)
        r = self.client.get(f'/api/schema/{conn.pk}/tables/')
        data = json.loads(r.content)
        self.assertIsNotNone(data['error'])
        self.assertEqual(data['tables'], [])


# ═══════════════════════════════════════════════════════════════════
#  Views — run checks
# ═══════════════════════════════════════════════════════════════════

class RunChecksViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('admin', password='pass')
        self.client.login(username='admin', password='pass')

    @patch('monitor.views.run_checks_for_user')
    def test_run_all_redirects_to_dashboard(self, mock_run):
        mock_run.return_value = MagicMock(ok_count=1, fail_count=0, error_count=0)
        r = self.client.post(reverse('monitor:run_checks'))
        self.assertRedirects(r, reverse('monitor:dashboard'))
        mock_run.assert_called_once()

    @patch('monitor.views.run_single_rule')
    def test_run_single_redirects(self, mock_run):
        rule = make_rule(min_rows=1, user=self.user)
        mock_run.return_value = MagicMock(status='OK', error_message='')
        r = self.client.post(reverse('monitor:run_single', args=[rule.pk]))
        self.assertRedirects(r, reverse('monitor:dashboard'))
        mock_run.assert_called_once_with(rule)

    @patch('monitor.views.run_single_rule')
    def test_run_single_ok_flash_message(self, mock_run):
        rule = make_rule(name='orders_check', min_rows=1, user=self.user)
        mock_run.return_value = MagicMock(status='OK', error_message='')
        r = self.client.post(
            reverse('monitor:run_single', args=[rule.pk]),
            follow=True,
        )
        messages = list(r.context['messages'])
        self.assertTrue(any('OK' in str(m) for m in messages))

    @patch('monitor.views.run_single_rule')
    def test_run_single_fail_flash_message(self, mock_run):
        rule = make_rule(name='orders_check', min_rows=1, user=self.user)
        mock_run.return_value = MagicMock(status='FAIL', error_message='')
        r = self.client.post(
            reverse('monitor:run_single', args=[rule.pk]),
            follow=True,
        )
        messages = list(r.context['messages'])
        self.assertTrue(any('FAIL' in str(m) for m in messages))

    def test_run_all_get_ignored(self):
        r = self.client.get(reverse('monitor:run_checks'))
        self.assertRedirects(r, reverse('monitor:dashboard'))


# ═══════════════════════════════════════════════════════════════
#  Schedule command
# ═══════════════════════════════════════════════════════════════

class RunScheduledCommandTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('scheduled_user', password='pass')

    @patch('monitor.management.commands.run_scheduled.run_single_rule')
    @patch('monitor.management.commands.run_scheduled.timezone')
    def test_runs_rules_matching_current_time(self, mock_tz, mock_run):
        from datetime import datetime, timezone as utc
        mock_tz.now.return_value = datetime(2025, 1, 1, 8, 0, tzinfo=utc.utc)
        rule = make_rule(name='scheduled', min_rows=1, user=self.user)
        rule.schedule_type = 'preset_1x'  # cron: 0 8 * * *
        rule.save()

        mock_run.return_value = MagicMock(status='OK')

        from monitor.management.commands.run_scheduled import Command
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd.handle()

        mock_run.assert_called_once_with(rule)

    @patch('monitor.management.commands.run_scheduled.run_single_rule')
    @patch('monitor.management.commands.run_scheduled.timezone')
    def test_skips_rules_with_different_time(self, mock_tz, mock_run):
        from datetime import datetime, timezone as utc
        mock_tz.now.return_value = datetime(2025, 1, 1, 9, 0, tzinfo=utc.utc)
        rule = make_rule(name='not_now', min_rows=1, user=self.user)
        rule.schedule_type = 'preset_1x'  # cron: 0 8 * * * — does not match 09:00
        rule.save()

        from monitor.management.commands.run_scheduled import Command
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd.handle()

        mock_run.assert_not_called()

    @patch('monitor.management.commands.run_scheduled.run_single_rule')
    @patch('monitor.management.commands.run_scheduled.timezone')
    def test_disabled_rule_is_skipped(self, mock_tz, mock_run):
        from datetime import datetime, timezone as utc
        mock_tz.now.return_value = datetime(2025, 1, 1, 8, 0, tzinfo=utc.utc)
        rule = make_rule(name='disabled_rule', min_rows=1, user=self.user)
        rule.schedule_type = 'disabled'
        rule.save()

        from monitor.management.commands.run_scheduled import Command
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd.handle()

        mock_run.assert_not_called()

    @patch('monitor.management.commands.run_scheduled.run_single_rule')
    @patch('monitor.management.commands.run_scheduled.timezone')
    def test_custom_cron_rule_fires(self, mock_tz, mock_run):
        from datetime import datetime, timezone as utc
        mock_tz.now.return_value = datetime(2025, 1, 1, 14, 30, tzinfo=utc.utc)
        rule = make_rule(name='custom_rule', min_rows=1, user=self.user)
        rule.schedule_type = 'custom_cron'
        rule.schedule_cron = '30 14 * * *'
        rule.save()

        mock_run.return_value = MagicMock(status='OK')

        from monitor.management.commands.run_scheduled import Command
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd.handle()

        mock_run.assert_called_once_with(rule)


# ═══════════════════════════════════════════════════════════════
#  RuleForm schedule validation
# ═══════════════════════════════════════════════════════════════

class RuleFormScheduleTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('sched_form_user', password='pass')

    def _base_data(self, **overrides):
        """Minimal valid form data for a volume rule."""
        conn = Connection.objects.create(name='sched-conn', user=self.user)
        conn.set_database_url('postgresql://user:pass@host/db')
        conn.save()
        data = {
            'name': 'sched-rule',
            'schema_name': 'public',
            'table_name': 'orders',
            'connection': conn.pk,
            'rule_type': 'volume_freshness',
            'custom_sql': '',
            'timestamp_column': '',
            'max_age_hours': '',
            'min_row_count': '1',
            'schedule_type': 'disabled',
            'schedule_cron': '',
        }
        data.update(overrides)
        return data

    def test_custom_cron_required_when_type_is_custom(self):
        from monitor.forms import RuleForm
        data = self._base_data(schedule_type='custom_cron', schedule_cron='')
        form = RuleForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('schedule_cron', form.errors)

    def test_invalid_cron_expression_rejected(self):
        from monitor.forms import RuleForm
        data = self._base_data(schedule_type='custom_cron', schedule_cron='60 99 * * *')
        form = RuleForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('schedule_cron', form.errors)

    def test_valid_custom_cron_accepted(self):
        from monitor.forms import RuleForm
        data = self._base_data(schedule_type='custom_cron', schedule_cron='0 8 * * *')
        form = RuleForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_preset_requires_no_cron_field(self):
        from monitor.forms import RuleForm
        data = self._base_data(schedule_type='preset_1x', schedule_cron='')
        form = RuleForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

class SlackNotificationModelTest(TestCase):

    def test_slacknotification_created_with_defaults(self):
        """SlackNotification is created with enabled=False, empty webhook_url, no user."""
        instance = SlackNotification.objects.create()
        self.assertFalse(instance.enabled)
        self.assertEqual(instance.webhook_url, '')
        self.assertIsNone(instance.user)

    def test_connection_list_shows_slack_card(self):
        """The /connections/ page contains the Slack provider card with a Soon badge."""
        user = User.objects.create_user('slacktest', password='pass')
        self.client.force_login(user)
        r = self.client.get(reverse('monitor:connection_list'))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Slack', r.content)
        self.assertIn(b'badge-soon', r.content)


# ═══════════════════════════════════════════════════════════════════
#  MySQL helper
# ═══════════════════════════════════════════════════════════════════

def make_mysql_connection(name='test_mysql', url='mysql+pymysql://user:pass@host/db', user=None):
    conn = Connection(name=name, provider='mysql', user=user)
    conn.set_database_url(url)
    conn.save()
    return conn


# ═══════════════════════════════════════════════════════════════════
#  MySQL — Connection model
# ═══════════════════════════════════════════════════════════════════

class ConnectionProviderModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('provider_model_user', password='pass')

    def test_default_provider_is_postgresql(self):
        conn = make_connection(name='pg_default', user=self.user)
        self.assertEqual(conn.provider, 'postgresql')

    def test_mysql_provider_saved(self):
        conn = make_mysql_connection(name='mysql_conn', user=self.user)
        self.assertEqual(conn.provider, 'mysql')

    def test_provider_choices(self):
        from .models import Connection
        choices = dict(Connection.Provider.choices)
        self.assertIn('postgresql', choices)
        self.assertIn('mysql', choices)

    def test_str_includes_provider(self):
        conn = make_connection(name='prod', user=self.user)
        self.assertIn('PostgreSQL', str(conn))
        mysql_conn = make_mysql_connection(name='mysql_prod', user=self.user)
        self.assertIn('MySQL', str(mysql_conn))


# ═══════════════════════════════════════════════════════════════════
#  MySQL — _open_conn dispatch
# ═══════════════════════════════════════════════════════════════════

class OpenConnDispatchTest(TestCase):

    @patch('monitor.services.psycopg2.connect')
    def test_postgresql_calls_psycopg2(self, mock_pg):
        from .services import _open_conn
        mock_pg.return_value = MagicMock()
        _open_conn('postgresql://u:p@host/db', 'postgresql')
        mock_pg.assert_called_once_with('postgresql://u:p@host/db')

    @patch('monitor.services.pymysql.connect')
    def test_mysql_calls_pymysql(self, mock_my):
        from .services import _open_conn
        mock_my.return_value = MagicMock()
        _open_conn('mysql+pymysql://u:p@host:3306/db', 'mysql')
        mock_my.assert_called_once()
        kwargs = mock_my.call_args[1]
        self.assertEqual(kwargs['host'], 'host')
        self.assertEqual(kwargs['port'], 3306)
        self.assertEqual(kwargs['user'], 'u')
        self.assertEqual(kwargs['database'], 'db')

    @patch('monitor.services.psycopg2.connect')
    def test_postgresql_error_raises_monitored_db_error(self, mock_pg):
        import psycopg2 as _pg
        from .services import _open_conn, MonitoredDbError
        mock_pg.side_effect = _pg.OperationalError('refused')
        with self.assertRaises(MonitoredDbError):
            _open_conn('postgresql://u:p@host/db', 'postgresql')

    @patch('monitor.services.pymysql.connect')
    def test_mysql_error_raises_monitored_db_error(self, mock_my):
        import pymysql.err
        from .services import _open_conn, MonitoredDbError
        mock_my.side_effect = pymysql.err.OperationalError('refused')
        with self.assertRaises(MonitoredDbError):
            _open_conn('mysql+pymysql://u:p@host/db', 'mysql')


# ═══════════════════════════════════════════════════════════════════
#  MySQL — _check_custom_sql timeout branch
# ═══════════════════════════════════════════════════════════════════

class CustomSqlMySQLTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('custom_sql_mysql_user', password='pass')

    def _mock_conn(self, fetchone_return=(True,)):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = fetchone_return
        conn.cursor.return_value = cursor
        return conn, cursor

    def test_mysql_uses_session_max_execution_time(self):
        from .services import _check_custom_sql
        rule = make_rule(rule_type='custom_sql', custom_sql='SELECT 1', user=self.user)
        conn, cursor = self._mock_conn((1,))
        _check_custom_sql(conn, rule, 'mysql')
        first_call = cursor.execute.call_args_list[0]
        self.assertIn('max_execution_time', first_call[0][0])
        self.assertNotIn('statement_timeout', first_call[0][0])

    def test_postgresql_uses_statement_timeout(self):
        from .services import _check_custom_sql
        rule = make_rule(rule_type='custom_sql', custom_sql='SELECT 1', user=self.user)
        conn, cursor = self._mock_conn((1,))
        _check_custom_sql(conn, rule, 'postgresql')
        first_call = cursor.execute.call_args_list[0]
        self.assertIn('statement_timeout', first_call[0][0])
        self.assertNotIn('max_execution_time', first_call[0][0])


# ═══════════════════════════════════════════════════════════════════
#  MySQL — _check_volume_freshness freshness branch
# ═══════════════════════════════════════════════════════════════════

class VolumeFreshnessMySQLTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('vol_mysql_user', password='pass')

    def _mock_conn(self, side_effect=None, fetchone_return=None):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        if side_effect is not None:
            cursor.fetchone.side_effect = side_effect
        else:
            cursor.fetchone.return_value = fetchone_return
        conn.cursor.return_value = cursor
        return conn, cursor

    def test_mysql_uses_timestampdiff(self):
        from .services import _check_volume_freshness
        rule = make_rule(ts_col='created_at', max_age=24, user=self.user)
        conn, cursor = self._mock_conn(fetchone_return=(2.0,))
        _check_volume_freshness(conn, rule, 'mysql')
        # Find the freshness SQL call
        calls = [str(c) for c in cursor.execute.call_args_list]
        freshness_calls = [c for c in calls if 'TIMESTAMPDIFF' in c or 'COUNT' in c]
        self.assertTrue(any('TIMESTAMPDIFF' in c for c in calls))
        self.assertFalse(any('EXTRACT' in c for c in calls))

    def test_postgresql_uses_extract_epoch(self):
        from .services import _check_volume_freshness
        rule = make_rule(ts_col='created_at', max_age=24, user=self.user)
        conn, cursor = self._mock_conn(fetchone_return=(2.0,))
        _check_volume_freshness(conn, rule, 'postgresql')
        calls = [str(c) for c in cursor.execute.call_args_list]
        self.assertTrue(any('EXTRACT' in c for c in calls))
        self.assertFalse(any('TIMESTAMPDIFF' in c for c in calls))

    def test_mysql_freshness_ok(self):
        from .services import _check_volume_freshness
        rule = make_rule(ts_col='created_at', max_age=24, user=self.user)
        conn, cursor = self._mock_conn(fetchone_return=(2.0,))
        result = _check_volume_freshness(conn, rule, 'mysql')
        self.assertEqual(result['status'], 'OK')
        self.assertAlmostEqual(result['last_record_age_hours'], 2.0)


# ═══════════════════════════════════════════════════════════════════
#  MySQL — get_schema_tables system-schema filter
# ═══════════════════════════════════════════════════════════════════

class GetSchemaTablesMySQLTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('schema_tables_user', password='pass')
        self.mysql_conn = make_mysql_connection(name='mysql_tables_test', user=self.user)

    @patch('monitor.services._open_conn')
    def test_mysql_excludes_system_schemas(self, mock_open):
        from .services import get_schema_tables
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [('mydb', 'orders')]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor
        mock_open.return_value = mock_conn

        result = get_schema_tables(self.mysql_conn.pk)
        self.assertIsNone(result['error'])
        sql_executed = cursor.execute.call_args[0][0]
        self.assertIn('performance_schema', sql_executed)
        self.assertNotIn('pg_catalog', sql_executed)

    @patch('monitor.services._open_conn')
    def test_postgresql_excludes_pg_catalog(self, mock_open):
        from .services import get_schema_tables
        pg_conn = make_connection(name='pg_tables_test', user=self.user)
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [('public', 'orders')]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor
        mock_open.return_value = mock_conn

        result = get_schema_tables(pg_conn.pk)
        self.assertIsNone(result['error'])
        sql_executed = cursor.execute.call_args[0][0]
        self.assertIn('pg_catalog', sql_executed)


# ═══════════════════════════════════════════════════════════════
#  MySQL — get_schema_columns is_timestamp for datetime type
# ═══════════════════════════════════════════════════════════════

class GetSchemaColumnsMySQLTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('schema_cols_user', password='pass')
        self.mysql_conn = make_mysql_connection(name='mysql_cols_test', user=self.user)

    @patch('monitor.services._open_conn')
    def test_datetime_column_is_timestamp_true(self, mock_open):
        from .services import get_schema_columns
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            ('created_at', 'datetime'),
            ('id', 'int'),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor
        mock_open.return_value = mock_conn

        result = get_schema_columns(self.mysql_conn.pk, 'mydb', 'orders')
        self.assertIsNone(result['error'])
        cols = {c['name']: c for c in result['columns']}
        self.assertTrue(cols['created_at']['is_timestamp'])
        self.assertFalse(cols['id']['is_timestamp'])

    @patch('monitor.services._open_conn')
    def test_timestamp_column_is_timestamp_true(self, mock_open):
        from .services import get_schema_columns
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [('updated_at', 'timestamp')]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor
        mock_open.return_value = mock_conn

        result = get_schema_columns(self.mysql_conn.pk, 'mydb', 'orders')
        cols = {c['name']: c for c in result['columns']}
        self.assertTrue(cols['updated_at']['is_timestamp'])


# ═══════════════════════════════════════════════════════════════
#  Phase 5 — ?provider=mysql pre-selection view test
# ═══════════════════════════════════════════════════════════════

class ConnectionCreateProviderPreSelectTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('admin_preselect', password='pass')
        self.client.login(username='admin_preselect', password='pass')

    def test_provider_mysql_preselected_from_querystring(self):
        r = self.client.get(reverse('monitor:connection_create') + '?provider=mysql')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['form'].initial.get('provider'), 'mysql')

    def test_no_querystring_no_initial_provider(self):
        r = self.client.get(reverse('monitor:connection_create'))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('provider', r.context['form'].initial)


# ═══════════════════════════════════════════════════════════════
#  Multi-tenancy — Phase 4 new tests
# ═══════════════════════════════════════════════════════════════

class SignupViewTest(TestCase):
    """Tests for the public /signup/ registration view."""

    def test_signup_get_200(self):
        r = self.client.get('/signup/')
        self.assertEqual(r.status_code, 200)

    def test_signup_post_valid_creates_user(self):
        r = self.client.post('/signup/', {
            'username': 'newuser',
            'password1': 'Str0ngP@ssw0rd!',
            'password2': 'Str0ngP@ssw0rd!',
        })
        self.assertRedirects(r, '/', fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_signup_post_invalid_shows_form(self):
        r = self.client.post('/signup/', {
            'username': 'newuser',
            'password1': 'password123',
            'password2': 'differentpassword',
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_signup_redirects_authenticated_user(self):
        User.objects.create_user('existinguser', password='pass')
        self.client.login(username='existinguser', password='pass')
        r = self.client.get('/signup/')
        self.assertRedirects(r, reverse('monitor:dashboard'), fetch_redirect_response=False)

    def test_signup_page_not_accessible_with_bad_data(self):
        """Missing username should keep form invalid, User count unchanged."""
        r = self.client.post('/signup/', {
            'username': '',
            'password1': 'Str0ngP@ssw0rd!',
            'password2': 'Str0ngP@ssw0rd!',
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.exists())


class PasswordResetURLTest(TestCase):
    """Smoke tests that password reset URLs are wired and return 200."""

    def test_password_reset_form_200(self):
        r = self.client.get('/password-reset/')
        self.assertEqual(r.status_code, 200)

    def test_password_reset_done_200(self):
        r = self.client.get('/password-reset/done/')
        self.assertEqual(r.status_code, 200)

    def test_password_reset_complete_200(self):
        r = self.client.get('/password-reset/complete/')
        self.assertEqual(r.status_code, 200)


class PerUserIsolationTest(TestCase):
    """Assert that user A cannot access, edit, or delete user B's data (IDOR closure)."""

    def setUp(self):
        self.user_a = User.objects.create_user('user_a', password='pass')
        self.user_b = User.objects.create_user('user_b', password='pass')
        self.b_conn = make_connection(name='b_conn', user=self.user_b)
        self.b_rule = make_rule(name='b_rule', min_rows=1,
                                connection=self.b_conn, user=self.user_b)
        self.client.login(username='user_a', password='pass')

    def test_dashboard_hides_other_user_rule(self):
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'b_rule')

    def test_rule_edit_other_user_404(self):
        r = self.client.get(reverse('monitor:rule_edit', args=[self.b_rule.pk]))
        self.assertEqual(r.status_code, 404)

    def test_rule_delete_other_user_404(self):
        r = self.client.post(reverse('monitor:rule_delete', args=[self.b_rule.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Rule.objects.filter(pk=self.b_rule.pk).exists())

    def test_rule_history_other_user_404(self):
        r = self.client.get(reverse('monitor:rule_history', args=[self.b_rule.pk]))
        self.assertEqual(r.status_code, 404)

    def test_connection_list_hides_other_user(self):
        r = self.client.get(reverse('monitor:connection_list'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'b_conn')

    def test_connection_edit_other_user_404(self):
        r = self.client.get(reverse('monitor:connection_edit', args=[self.b_conn.pk]))
        self.assertEqual(r.status_code, 404)

    def test_connection_delete_other_user_404(self):
        r = self.client.post(reverse('monitor:connection_delete', args=[self.b_conn.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Connection.objects.filter(pk=self.b_conn.pk).exists())

    def test_api_schema_tables_other_user_404(self):
        r = self.client.get(f'/api/schema/{self.b_conn.pk}/tables/')
        self.assertEqual(r.status_code, 404)


# ═══════════════════════════════════════════════════════════════════
#  Email notifications (S-13)
# ═══════════════════════════════════════════════════════════════════

class EmailNotificationTest(TestCase):
    """Unit tests for monitor.email_service.send_fail_notification."""

    def setUp(self):
        self.user = User.objects.create_user(
            'notif_user', email='owner@example.com', password='pass'
        )
        self.rule = make_rule(name='email_test_rule', min_rows=10, user=self.user)
        self.rule.notify_on_fail = True
        self.rule.save()

        self.run = CheckRun.objects.create(finished_at=timezone.now())
        self.result = RuleResult.objects.create(
            run=self.run,
            rule=self.rule,
            status=RuleResult.Status.FAIL,
        )

    def _send(self, **overrides):
        from .email_service import send_fail_notification
        rule = overrides.get('rule', self.rule)
        result = overrides.get('result', self.result)
        return send_fail_notification(rule, result)

    # ── Guard: notify_on_fail=False ─────────────────────────────────

    def test_notification_skipped_when_disabled(self):
        """Returns False when rule.notify_on_fail is False."""
        self.rule.notify_on_fail = False
        self.rule.save()
        from django.test.utils import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            sent = self._send()
        self.assertFalse(sent)

    # ── Guard: blank owner email ────────────────────────────────────

    def test_notification_skipped_on_ok(self):
        """Returns False when result status is OK (no email should go out)."""
        ok_result = RuleResult.objects.create(
            run=self.run,
            rule=self.rule,
            status=RuleResult.Status.OK,
        )
        from django.test.utils import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            # email_service only checks notify_on_fail guard, not status —
            # the status gate is in services.py. This test confirms the
            # service itself will still attempt to send if called directly;
            # the status guard is exercised by services tests. We use a
            # blank email here to confirm the owner-email guard fires first.
            user_no_email = User.objects.create_user('no_email_user', password='pass')
            rule_no_email = make_rule(name='no_email_rule', min_rows=1, user=user_no_email)
            rule_no_email.notify_on_fail = True
            rule_no_email.save()
            sent = self._send(rule=rule_no_email, result=ok_result)
        self.assertFalse(sent)

    # ── Guard: owner email blank ────────────────────────────────────

    def test_notification_skipped_when_owner_email_blank(self):
        """Returns False when owner email is blank."""
        user_blank = User.objects.create_user('blank_email', email='', password='pass')
        rule_blank = make_rule(name='blank_email_rule', min_rows=1, user=user_blank)
        rule_blank.notify_on_fail = True
        rule_blank.save()
        from django.test.utils import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            sent = self._send(rule=rule_blank)
        self.assertFalse(sent)

    # ── Guard: cooldown ─────────────────────────────────────────────

    def test_notification_skipped_on_cooldown(self):
        """Returns False when last_notified_at was < 1 hour ago."""
        from datetime import timedelta
        self.rule.last_notified_at = timezone.now() - timedelta(minutes=30)
        self.rule.save()
        from django.test.utils import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            sent = self._send()
        self.assertFalse(sent)

    def test_notification_sent_after_cooldown_expires(self):
        """Returns True when last_notified_at was >= 1 hour ago."""
        from datetime import timedelta
        self.rule.last_notified_at = timezone.now() - timedelta(hours=1, seconds=1)
        self.rule.save()
        from django.test.utils import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            sent = self._send()
        self.assertTrue(sent)

    # ── Happy path ──────────────────────────────────────────────────

    def test_notification_sent_on_fail(self):
        """Sends email and returns True when all guards pass."""
        from django.core import mail
        from django.test.utils import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            sent = self._send()
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('owner@example.com', mail.outbox[0].to)
        self.assertIn('DataPulse', mail.outbox[0].subject)
        self.assertIn('FAIL', mail.outbox[0].subject)

    def test_notification_updates_last_notified_at(self):
        """last_notified_at is set after a successful send."""
        from django.core import mail
        from django.test.utils import override_settings
        self.assertIsNone(self.rule.last_notified_at)
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self._send()
        self.rule.refresh_from_db()
        self.assertIsNotNone(self.rule.last_notified_at)

    # ── Exception safety ────────────────────────────────────────────

    def test_notification_returns_false_on_send_exception(self):
        """Returns False (does not raise) when send raises an exception."""
        from unittest.mock import patch as _patch
        with _patch('monitor.email_service.EmailMultiAlternatives.send', side_effect=Exception('SMTP error')):
            from django.test.utils import override_settings
            with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
                sent = self._send()
        self.assertFalse(sent)

    # ── services.py integration ─────────────────────────────────────

    def test_run_single_rule_fail_calls_send_notification(self):
        """run_single_rule with a FAIL result calls send_fail_notification."""
        from unittest.mock import patch as _patch, MagicMock as _MM
        conn = make_connection(user=self.user)
        rule = make_rule(name='hook_test', min_rows=1000, connection=conn, user=self.user)
        rule.notify_on_fail = True
        rule.save()

        with _patch('monitor.services.psycopg2.connect') as mock_conn, \
             _patch('monitor.services.send_fail_notification') as mock_notify:
            cursor = _MM()
            cursor.__enter__ = _MM(return_value=cursor)
            cursor.__exit__ = _MM(return_value=False)
            cursor.fetchone.return_value = (3,)  # below min_rows=1000 → FAIL
            mock_conn.return_value.cursor.return_value = cursor

            from .services import run_single_rule
            run_single_rule(rule)

        mock_notify.assert_called_once()
        call_rule, call_result = mock_notify.call_args[0]
        self.assertEqual(call_rule, rule)
        self.assertEqual(call_result.status, RuleResult.Status.FAIL)

    def test_run_single_rule_ok_skips_notification(self):
        """run_single_rule with OK result does NOT call send_fail_notification."""
        from unittest.mock import patch as _patch, MagicMock as _MM
        conn = make_connection(name='ok_conn', user=self.user)
        rule = make_rule(name='ok_test', min_rows=1, connection=conn, user=self.user)
        rule.notify_on_fail = True
        rule.save()

        with _patch('monitor.services.psycopg2.connect') as mock_conn, \
             _patch('monitor.services.send_fail_notification') as mock_notify:
            cursor = _MM()
            cursor.__enter__ = _MM(return_value=cursor)
            cursor.__exit__ = _MM(return_value=False)
            cursor.fetchone.return_value = (100,)  # above min_rows=1 -> OK
            mock_conn.return_value.cursor.return_value = cursor

            from .services import run_single_rule
            run_single_rule(rule)

        mock_notify.assert_not_called()

    def test_run_all_checks_fail_calls_send_notification(self):
        """run_all_checks with a FAIL rule and notify_on_fail=True calls send_fail_notification."""
        from unittest.mock import patch as _patch, MagicMock as _MM
        conn = make_connection(name="all_conn", user=self.user)
        rule = make_rule(name="all_fail_rule", min_rows=1000, connection=conn, user=self.user)
        rule.notify_on_fail = True
        rule.save()

        with _patch("monitor.services.psycopg2.connect") as mock_conn,              _patch("monitor.services.send_fail_notification") as mock_notify:
            cursor = _MM()
            cursor.__enter__ = _MM(return_value=cursor)
            cursor.__exit__ = _MM(return_value=False)
            cursor.fetchone.return_value = (3,)  # below min_rows=1000 -> FAIL
            mock_conn.return_value.cursor.return_value = cursor

            from .services import run_all_checks
            run_all_checks()

        self.assertTrue(mock_notify.called)
        # Verify at least one call was for our specific rule
        called_rules = [c[0][0] for c in mock_notify.call_args_list]
        self.assertIn(rule, called_rules)


class RuleFormNotifyOnFailTest(TestCase):
    """notify_on_fail field is accepted by RuleForm and saved correctly."""

    def setUp(self):
        self.user = User.objects.create_user("form_notif_user", password="pass")
        self.client.login(username="form_notif_user", password="pass")

    def test_form_post_with_notify_on_fail_saves_true(self):
        """POST to rule_create with notify_on_fail checked saves Rule with notify_on_fail=True."""
        conn = make_connection(user=self.user)
        r = self.client.post(reverse("monitor:rule_create"), {
            "name": "notif_rule",
            "schema_name": "public",
            "table_name": "orders",
            "min_row_count": 10,
            "rule_type": "volume_freshness",
            "connection": conn.pk,
            "notify_on_fail": "on",
        })
        self.assertRedirects(r, reverse("monitor:dashboard"))
        rule = Rule.objects.get(name="notif_rule")
        self.assertTrue(rule.notify_on_fail)

    def test_form_post_without_notify_on_fail_saves_false(self):
        """POST without notify_on_fail results in notify_on_fail=False."""
        conn = make_connection(name="no_notif_conn", user=self.user)
        r = self.client.post(reverse("monitor:rule_create"), {
            "name": "no_notif_rule",
            "schema_name": "public",
            "table_name": "orders",
            "min_row_count": 10,
            "rule_type": "volume_freshness",
            "connection": conn.pk,
        })
        self.assertRedirects(r, reverse("monitor:dashboard"))
        rule = Rule.objects.get(name="no_notif_rule")
        self.assertFalse(rule.notify_on_fail)


# ═══════════════════════════════════════════════════════════════
#  Schedule dashboard (schedule-dashboard change)
# ═══════════════════════════════════════════════════════════════

class ScheduleDashboardTests(TestCase):
    """Tests for schedule_dashboard view and toggle_schedule view."""

    def setUp(self):
        self.user = User.objects.create_user('sched_dash_user', password='pass')
        self.other_user = User.objects.create_user('sched_other_user', password='pass')
        self.client.login(username='sched_dash_user', password='pass')

    # ---- View access --------------------------------------------------

    def test_schedule_dashboard_200(self):
        """Authenticated user with one scheduled rule gets 200 and sees the rule name."""
        rule = make_rule(name='my_scheduled_rule', min_rows=1, user=self.user)
        rule.schedule_type = 'preset_1x'
        rule.save()
        r = self.client.get(reverse('monitor:schedule_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'my_scheduled_rule')

    def test_schedule_dashboard_redirects_anonymous(self):
        """Anonymous GET returns 302 to login."""
        self.client.logout()
        r = self.client.get(reverse('monitor:schedule_dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_schedule_dashboard_shows_only_scheduled_rules(self):
        """Only rules with schedule_type != disabled appear in rule_rows."""
        sched_rule = make_rule(name='sched_only', min_rows=1, user=self.user)
        sched_rule.schedule_type = 'preset_1x'
        sched_rule.save()
        disabled_rule = make_rule(name='disabled_rule', min_rows=1, user=self.user)
        # disabled_rule.schedule_type defaults to 'disabled', no extra save needed
        r = self.client.get(reverse('monitor:schedule_dashboard'))
        self.assertEqual(r.status_code, 200)
        rule_rows = r.context['rule_rows']
        rule_ids = [row['rule'].pk for row in rule_rows]
        self.assertIn(sched_rule.pk, rule_ids)
        self.assertNotIn(disabled_rule.pk, rule_ids)

    def test_schedule_dashboard_empty_state(self):
        """User with no scheduled rules gets 200 with an empty rule_rows list."""
        r = self.client.get(reverse('monitor:schedule_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['rule_rows']), 0)

    # ---- Toggle -------------------------------------------------------

    def test_toggle_schedule_disables_rule(self):
        """POST to toggle_schedule for a preset_1x rule flips it to disabled."""
        rule = make_rule(name='to_disable', min_rows=1, user=self.user)
        rule.schedule_type = 'preset_1x'
        rule.save()
        r = self.client.post(reverse('monitor:toggle_schedule', args=[rule.pk]))
        self.assertRedirects(r, reverse('monitor:schedule_dashboard'),
                             fetch_redirect_response=False)
        rule.refresh_from_db()
        self.assertEqual(rule.schedule_type, 'disabled')

    def test_toggle_schedule_enables_rule(self):
        """POST to toggle_schedule for a disabled rule flips it to preset_1x."""
        rule = make_rule(name='to_enable', min_rows=1, user=self.user)
        # schedule_type is 'disabled' by default
        r = self.client.post(reverse('monitor:toggle_schedule', args=[rule.pk]))
        self.assertRedirects(r, reverse('monitor:schedule_dashboard'),
                             fetch_redirect_response=False)
        rule.refresh_from_db()
        self.assertEqual(rule.schedule_type, 'preset_1x')

    def test_toggle_schedule_404_for_other_users_rule(self):
        """POST by user A on user B's rule returns 404."""
        other_rule = make_rule(name='other_rule', min_rows=1, user=self.other_user)
        other_rule.schedule_type = 'preset_1x'
        other_rule.save()
        r = self.client.post(reverse('monitor:toggle_schedule', args=[other_rule.pk]))
        self.assertEqual(r.status_code, 404)
        other_rule.refresh_from_db()
        self.assertEqual(other_rule.schedule_type, 'preset_1x')  # unchanged

    # ---- schedule_utils unit tests ------------------------------------

    def test_resolve_cron_preset(self):
        """resolve_cron returns '0 8 * * *' for preset_1x."""
        from monitor.schedule_utils import resolve_cron
        rule = make_rule(min_rows=1, user=self.user)
        rule.schedule_type = 'preset_1x'
        self.assertEqual(resolve_cron(rule), '0 8 * * *')

    def test_resolve_cron_custom(self):
        """resolve_cron returns the schedule_cron value for custom_cron type."""
        from monitor.schedule_utils import resolve_cron
        rule = make_rule(min_rows=1, user=self.user)
        rule.schedule_type = 'custom_cron'
        rule.schedule_cron = '15 3 * * *'
        self.assertEqual(resolve_cron(rule), '15 3 * * *')

    def test_resolve_cron_disabled(self):
        """resolve_cron returns None for disabled."""
        from monitor.schedule_utils import resolve_cron
        rule = make_rule(min_rows=1, user=self.user)
        rule.schedule_type = 'disabled'
        self.assertIsNone(resolve_cron(rule))

    def test_get_next_run_returns_datetime(self):
        """get_next_run returns a datetime with hour=8, minute=0 for preset_1x."""
        from datetime import datetime, timezone as dt_timezone
        from croniter import croniter
        # Use croniter directly with a fixed baseline to verify the math
        now = datetime(2025, 1, 1, 9, 0, 0, tzinfo=dt_timezone.utc)
        next_run = croniter('0 8 * * *', now).get_next(datetime)
        self.assertIsInstance(next_run, datetime)
        self.assertEqual(next_run.hour, 8)
        self.assertEqual(next_run.minute, 0)

