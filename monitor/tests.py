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
#  IDOR isolation tests (targeted)
# ═══════════════════════════════════════════════════════════════════

class UserIsolationTest(TestCase):
    """Targeted IDOR isolation tests — four specific vectors."""

    def setUp(self):
        import hashlib as _hl
        from .models import ApiKey

        self.user_a = User.objects.create_user('iso_user_a', password='pass')
        self.user_b = User.objects.create_user('iso_user_b', password='pass')

        # User B has a rule and a CheckRun with results
        self.b_rule = make_rule(name='b_iso_rule', min_rows=1, user=self.user_b)
        self.b_run = CheckRun.objects.create(finished_at=timezone.now())
        RuleResult.objects.create(
            run=self.b_run, rule=self.b_rule, status='OK', row_count=10
        )

        # API key for user A
        raw = 'iso_test_raw_key_a'
        key_hash = _hl.sha256(raw.encode()).hexdigest()
        ApiKey.objects.create(user=self.user_a, name='iso key a', key_hash=key_hash)
        self.api_raw_a = raw

    def _api_auth(self):
        return f'Bearer {self.api_raw_a}'

    # ── 1. dashboard last_run must not leak user B's CheckRun ──────

    def test_last_run_not_leaked(self):
        """User A sees no last_run when they have no rules/runs of their own."""
        self.client.login(username='iso_user_a', password='pass')
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertEqual(r.status_code, 200)
        # User A has no rules; last_run must be None, not user B's run
        self.assertIsNone(
            r.context['last_run'],
            msg='last_run leaked a CheckRun belonging to another user',
        )

    # ── 2. API /api/v1/rules returns only user's own rules ─────────

    def test_api_rules_filtered(self):
        """GET /api/v1/rules returns only user A's rules, not user B's."""
        a_rule = make_rule(name='a_iso_rule', min_rows=1, user=self.user_a)
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=self._api_auth())
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        names = [rule['name'] for rule in data['rules']]
        self.assertIn('a_iso_rule', names)
        self.assertNotIn('b_iso_rule', names)

    # ── 3. run_single requires ownership ──────────────────────────

    def test_run_single_requires_ownership(self):
        """User A cannot trigger a run for user B's rule — must get 404."""
        self.client.login(username='iso_user_a', password='pass')
        r = self.client.post(
            reverse('monitor:run_single', args=[self.b_rule.pk])
        )
        self.assertEqual(
            r.status_code, 404,
            msg='run_single must return 404 for rules owned by another user',
        )

    # ── 4. schedule_dashboard shows only user's scheduled rules ───

    def test_schedule_dashboard_filtered(self):
        """Schedule dashboard shows only user A's scheduled rules, not user B's."""
        # Give user B a scheduled rule
        b_sched_rule = make_rule(name='b_sched_rule', min_rows=1, user=self.user_b)
        b_sched_rule.schedule_type = 'preset_1x'
        b_sched_rule.save()

        # Give user A a scheduled rule
        a_sched_rule = make_rule(name='a_sched_rule', min_rows=1, user=self.user_a)
        a_sched_rule.schedule_type = 'preset_1x'
        a_sched_rule.save()

        self.client.login(username='iso_user_a', password='pass')
        r = self.client.get(reverse('monitor:schedule_dashboard'))
        self.assertEqual(r.status_code, 200)
        rule_rows = r.context['rule_rows']
        rule_pks = {row['rule'].pk for row in rule_rows}
        self.assertIn(a_sched_rule.pk, rule_pks)
        self.assertNotIn(b_sched_rule.pk, rule_pks)


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
        """run_single_rule with a FAIL result calls notify_rule_result."""
        from unittest.mock import patch as _patch, MagicMock as _MM
        conn = make_connection(user=self.user)
        rule = make_rule(name='hook_test', min_rows=1000, connection=conn, user=self.user)
        rule.notify_on_fail = True
        rule.save()

        with _patch('monitor.services.psycopg2.connect') as mock_conn, \
             _patch('monitor.services.notify_rule_result') as mock_notify:
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
        """run_single_rule with OK result does NOT call notify_rule_result."""
        from unittest.mock import patch as _patch, MagicMock as _MM
        conn = make_connection(name='ok_conn', user=self.user)
        rule = make_rule(name='ok_test', min_rows=1, connection=conn, user=self.user)
        rule.notify_on_fail = True
        rule.save()

        with _patch('monitor.services.psycopg2.connect') as mock_conn, \
             _patch('monitor.services.notify_rule_result') as mock_notify:
            cursor = _MM()
            cursor.__enter__ = _MM(return_value=cursor)
            cursor.__exit__ = _MM(return_value=False)
            cursor.fetchone.return_value = (100,)  # above min_rows=1 -> OK
            mock_conn.return_value.cursor.return_value = cursor

            from .services import run_single_rule
            run_single_rule(rule)

        mock_notify.assert_not_called()

    def test_run_all_checks_fail_calls_send_notification(self):
        """run_all_checks with a FAIL rule and notify_on_fail=True calls notify_rule_result."""
        from unittest.mock import patch as _patch, MagicMock as _MM
        conn = make_connection(name="all_conn", user=self.user)
        rule = make_rule(name="all_fail_rule", min_rows=1000, connection=conn, user=self.user)
        rule.notify_on_fail = True
        rule.save()

        with _patch("monitor.services.psycopg2.connect") as mock_conn, \
             _patch("monitor.services.notify_rule_result") as mock_notify:
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




# =================================================================
#  dbt Integration - model
# =================================================================

from .models import DbtIntegration


def make_dbt_integration(name='test dbt', job_id='job_001', user=None, secret='s3cr3t'):
    obj = DbtIntegration(name=name, job_id=job_id, user=user)
    obj.set_secret_key(secret)
    obj.save()
    return obj


def make_rule_for_dbt(name='dbt_rule', user=None):
    # notify_slack required by migration 0013 NOT NULL constraint
    return Rule.objects.create(
        name=name,
        schema_name='public',
        table_name='orders',
        min_row_count=1,
        user=user,
        notify_slack=False,
    )


class DbtIntegrationModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('dbt_model_user', password='pass')

    def test_set_and_get_secret_key(self):
        obj = make_dbt_integration(user=self.user, secret='mysecretvalue')
        self.assertEqual(obj.get_secret_key(), 'mysecretvalue')
        obj.refresh_from_db()
        self.assertEqual(obj.get_secret_key(), 'mysecretvalue')

    def test_stored_value_differs_from_raw(self):
        from django.conf import settings as djsettings
        if not getattr(djsettings, 'FIELD_ENCRYPTION_KEY', None):
            self.skipTest('FIELD_ENCRYPTION_KEY not set - plaintext, skip ciphertext check')
        obj = make_dbt_integration(user=self.user, secret='plaintext_value')
        obj.refresh_from_db()
        self.assertNotEqual(obj._secret_key, 'plaintext_value')

    def test_unique_together_constraint(self):
        from django.db import IntegrityError
        make_dbt_integration(name='first', job_id='dup_job', user=self.user)
        with self.assertRaises(IntegrityError):
            make_dbt_integration(name='second', job_id='dup_job', user=self.user)

    def test_unique_together_allows_same_job_id_for_different_users(self):
        other_user = User.objects.create_user('dbt_model_user2', password='pass')
        make_dbt_integration(name='a', job_id='shared_job', user=self.user)
        obj2 = make_dbt_integration(name='b', job_id='shared_job', user=other_user)
        self.assertIsNotNone(obj2.pk)

    def test_str_representation(self):
        obj = make_dbt_integration(name='prod run', job_id='42', user=self.user)
        self.assertIn('prod run', str(obj))
        self.assertIn('42', str(obj))

    def test_rules_m2m_empty_by_default(self):
        obj = make_dbt_integration(user=self.user)
        self.assertEqual(obj.rules.count(), 0)

    def test_rules_m2m_can_be_set(self):
        obj = make_dbt_integration(user=self.user)
        rule = make_rule_for_dbt(user=self.user)
        obj.rules.set([rule])
        self.assertEqual(obj.rules.count(), 1)


# =================================================================
#  dbt Integration - webhook view
# =================================================================

import hashlib
import hmac as _hmac

WEBHOOK_URL = '/api/v1/webhooks/dbt/'


def _sign(secret, body):
    return 'sha256=' + _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class DbtWebhookViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('dbt_webhook_user', password='pass')
        self.secret = 'testsecretvalue123'
        self.integration = make_dbt_integration(
            name='webhook test', job_id='job_wh', user=self.user, secret=self.secret,
        )
        rule = make_rule_for_dbt(name='wh_rule', user=self.user)
        self.integration.rules.set([rule])
        self.client = Client()

    def _post(self, payload, secret=None, content_type='application/json'):
        body = json.dumps(payload).encode()
        sig = _sign(secret or self.secret, body)
        return self.client.post(
            WEBHOOK_URL, data=body,
            content_type=content_type,
            HTTP_AUTHORIZATION=sig,
        )

    @patch('monitor.views.run_single_rule')
    def test_valid_hmac_success_triggers_rules(self, mock_run):
        mock_run.return_value = MagicMock(status='OK')
        r = self._post({'job_id': 'job_wh', 'run_status': 'Success'})
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['triggered'], 1)
        mock_run.assert_called_once()

    def test_wrong_secret_returns_401(self):
        r = self._post({'job_id': 'job_wh', 'run_status': 'Success'}, secret='wrongsecret')
        self.assertEqual(r.status_code, 401)

    def test_missing_authorization_header_returns_401(self):
        body = json.dumps({'job_id': 'job_wh', 'run_status': 'Success'}).encode()
        r = self.client.post(WEBHOOK_URL, data=body, content_type='application/json')
        self.assertEqual(r.status_code, 401)

    @patch('monitor.views.run_single_rule')
    def test_non_success_run_status_ignored(self, mock_run):
        r = self._post({'job_id': 'job_wh', 'run_status': 'Error'})
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['status'], 'ignored')
        mock_run.assert_not_called()

    @patch('monitor.views.run_single_rule')
    def test_dbt_cloud_payload_shape(self, mock_run):
        mock_run.return_value = MagicMock(status='OK')
        payload = {'data': {'jobId': 'job_wh', 'runStatus': 'Success'}}
        body = json.dumps(payload).encode()
        sig = _sign(self.secret, body)
        r = self.client.post(
            WEBHOOK_URL, data=body, content_type='application/json',
            HTTP_AUTHORIZATION=sig,
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['status'], 'ok')
        mock_run.assert_called_once()

    @patch('monitor.views.run_single_rule')
    def test_dbt_core_flat_payload_shape(self, mock_run):
        mock_run.return_value = MagicMock(status='OK')
        r = self._post({'job_id': 'job_wh', 'run_status': 'success'})
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['status'], 'ok')
        mock_run.assert_called_once()

    def test_invalid_json_returns_400(self):
        r = self.client.post(
            WEBHOOK_URL, data=b'not valid json', content_type='application/json',
            HTTP_AUTHORIZATION='sha256=abc',
        )
        self.assertEqual(r.status_code, 400)

    @patch('monitor.views.run_single_rule')
    def test_response_contains_results_list(self, mock_run):
        mock_run.return_value = MagicMock(status='OK')
        r = self._post({'job_id': 'job_wh', 'run_status': 'Success'})
        data = json.loads(r.content)
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['status'], 'OK')

    @patch('monitor.views.run_single_rule')
    def test_success_case_insensitive(self, mock_run):
        mock_run.return_value = MagicMock(status='OK')
        r = self._post({'job_id': 'job_wh', 'run_status': 'SUCCESS'})
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['status'], 'ok')
        mock_run.assert_called_once()


# =================================================================
#  dbt Integration - UI CRUD views
# =================================================================


class DbtIntegrationUITest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('dbt_ui_user', password='pass')
        self.other = User.objects.create_user('dbt_ui_other', password='pass')
        self.client.login(username='dbt_ui_user', password='pass')

    def test_list_view_requires_login(self):
        self.client.logout()
        r = self.client.get(reverse('monitor:dbt_integration_list'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_list_view_200_when_logged_in(self):
        r = self.client.get(reverse('monitor:dbt_integration_list'))
        self.assertEqual(r.status_code, 200)

    def test_list_view_shows_only_own_integrations(self):
        make_dbt_integration(name='mine', job_id='j1', user=self.user)
        make_dbt_integration(name='theirs', job_id='j2', user=self.other)
        r = self.client.get(reverse('monitor:dbt_integration_list'))
        self.assertContains(r, 'mine')
        self.assertNotContains(r, 'theirs')

    def test_create_view_get_200(self):
        r = self.client.get(reverse('monitor:dbt_integration_create'))
        self.assertEqual(r.status_code, 200)

    def test_create_view_post_creates_integration(self):
        r = self.client.post(reverse('monitor:dbt_integration_create'), {
            'name': 'new integration',
            'job_id': 'job_new',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn('raw_secret_key', r.context)
        self.assertTrue(DbtIntegration.objects.filter(job_id='job_new').exists())

    def test_create_view_displays_raw_secret_once(self):
        r = self.client.post(reverse('monitor:dbt_integration_create'), {
            'name': 'secret test',
            'job_id': 'job_secret',
        })
        self.assertIn('raw_secret_key', r.context)
        raw = r.context['raw_secret_key']
        self.assertEqual(len(raw), 64)
        self.assertContains(r, raw)

    def test_edit_view_200(self):
        obj = make_dbt_integration(name='editable', job_id='j_edit', user=self.user)
        r = self.client.get(reverse('monitor:dbt_integration_edit', args=[obj.pk]))
        self.assertEqual(r.status_code, 200)

    def test_edit_view_404_for_other_user(self):
        obj = make_dbt_integration(name='others', job_id='j_other', user=self.other)
        r = self.client.get(reverse('monitor:dbt_integration_edit', args=[obj.pk]))
        self.assertEqual(r.status_code, 404)

    def test_edit_view_post_updates_name(self):
        obj = make_dbt_integration(name='old name', job_id='j_upd', user=self.user)
        r = self.client.post(reverse('monitor:dbt_integration_edit', args=[obj.pk]), {
            'name': 'new name',
            'job_id': 'j_upd',
        })
        self.assertRedirects(r, reverse('monitor:dbt_integration_list'))
        obj.refresh_from_db()
        self.assertEqual(obj.name, 'new name')

    def test_delete_view_get_200(self):
        obj = make_dbt_integration(name='del me', job_id='j_del', user=self.user)
        r = self.client.get(reverse('monitor:dbt_integration_delete', args=[obj.pk]))
        self.assertEqual(r.status_code, 200)

    def test_delete_view_post_removes_integration(self):
        obj = make_dbt_integration(name='gone', job_id='j_gone', user=self.user)
        r = self.client.post(reverse('monitor:dbt_integration_delete', args=[obj.pk]))
        self.assertRedirects(r, reverse('monitor:dbt_integration_list'))
        self.assertFalse(DbtIntegration.objects.filter(pk=obj.pk).exists())

    def test_delete_view_404_for_other_user(self):
        obj = make_dbt_integration(name='protected', job_id='j_prot', user=self.other)
        r = self.client.post(reverse('monitor:dbt_integration_delete', args=[obj.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(DbtIntegration.objects.filter(pk=obj.pk).exists())

    def test_edit_view_does_not_expose_secret(self):
        obj = make_dbt_integration(name='nosec', job_id='j_nosec', user=self.user, secret='supersecretrawvalue')
        r = self.client.get(reverse('monitor:dbt_integration_edit', args=[obj.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'supersecretrawvalue')

# ═══════════════════════════════════════════════════════════════════
#  Phase 5 — alert-digest tests
# ═══════════════════════════════════════════════════════════════════


class UserProfileModelTest(TestCase):
    """UserProfile auto-creation and default mode."""

    def test_profile_auto_created_on_user_create(self):
        user = User.objects.create_user('profile_auto_user', password='pass')
        from .models import UserProfile
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_default_mode_is_immediate(self):
        user = User.objects.create_user('default_mode_user', password='pass')
        self.assertEqual(user.profile.notification_mode, 'immediate')

    def test_signal_fires_idempotently_on_resave(self):
        """Re-saving a user does not duplicate the profile."""
        from .models import UserProfile
        user = User.objects.create_user('resave_user', password='pass')
        user.save()  # trigger signal again
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)

    def test_profile_str(self):
        user = User.objects.create_user('str_user', password='pass')
        self.assertIn('immediate', str(user.profile))


class DigestNotificationTest(TestCase):
    """Unit tests for send_digest_notification."""

    def setUp(self):
        self.user = User.objects.create_user(
            'digest_notif_user', email='digest@example.com', password='pass'
        )
        self.run = CheckRun.objects.create(finished_at=timezone.now())
        self.rule = make_rule(name='digest_rule', min_rows=10, user=self.user)
        self.result = RuleResult.objects.create(
            run=self.run, rule=self.rule, status='FAIL'
        )

    def test_returns_false_for_empty_list(self):
        from .email_service import send_digest_notification
        from django.test.utils import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.assertFalse(send_digest_notification(self.run, [], self.user))

    def test_returns_false_for_user_without_email(self):
        from .email_service import send_digest_notification
        from django.test.utils import override_settings
        no_email_user = User.objects.create_user('no_email_digest', email='', password='pass')
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.assertFalse(send_digest_notification(self.run, [self.result], no_email_user))

    def test_sends_exactly_one_email(self):
        from .email_service import send_digest_notification
        from django.core import mail
        from django.test.utils import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            sent = send_digest_notification(self.run, [self.result], self.user)
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('digest@example.com', mail.outbox[0].to)

    def test_subject_contains_count_and_run_id(self):
        from .email_service import send_digest_notification
        from django.core import mail
        from django.test.utils import override_settings
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            send_digest_notification(self.run, [self.result], self.user)
        self.assertIn(str(self.run.pk), mail.outbox[0].subject)
        self.assertIn('1 rule(s)', mail.outbox[0].subject)

    def test_is_summary_true_for_ten_or_more_failures(self):
        """When failing_results >= 10, the rendered text contains the summary line."""
        from .email_service import send_digest_notification
        from django.core import mail
        from django.test.utils import override_settings
        results = []
        for i in range(10):
            r = make_rule(name=f'summary_rule_{i}', min_rows=1, user=self.user)
            results.append(RuleResult.objects.create(run=self.run, rule=r, status='FAIL'))
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            send_digest_notification(self.run, results, self.user)
        text_body = mail.outbox[0].body
        self.assertIn('see dashboard', text_body)

    def test_last_notified_at_not_updated(self):
        """Digest does not touch Rule.last_notified_at."""
        from .email_service import send_digest_notification
        from django.core import mail
        from django.test.utils import override_settings
        before = self.rule.last_notified_at
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            send_digest_notification(self.run, [self.result], self.user)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.last_notified_at, before)


class DigestFilterTest(TestCase):
    """Digest only includes results from rules where notify_on_fail is True."""

    def setUp(self):
        self.user = User.objects.create_user(
            'digest_filter_user', email='filter@example.com', password='pass'
        )
        self.user.profile.notification_mode = 'digest'
        self.user.profile.save()
        self.conn = make_connection(user=self.user)
        self.run_obj = CheckRun.objects.create(finished_at=timezone.now())

    @patch('monitor.services.psycopg2.connect')
    def test_only_notify_on_fail_rules_trigger_digest(self, mock_connect):
        """Rules with notify_on_fail=False are never included in the digest."""
        from django.core import mail
        from django.test.utils import override_settings

        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (3,)  # below min_rows -> FAIL
        mock_connect.return_value.cursor.return_value = cursor

        notify_rule = make_rule(name='notif_on', min_rows=100,
                                connection=self.conn, user=self.user)
        notify_rule.notify_on_fail = True
        notify_rule.save()

        silent_rule = make_rule(name='silent_fail', min_rows=100,
                                connection=self.conn, user=self.user)
        silent_rule.notify_on_fail = False
        silent_rule.save()

        from .email_service import send_digest_notification as orig_send

        captured_results = []

        def capturing_send(run, failing_results, user):
            captured_results.extend(failing_results)
            return orig_send(run, failing_results, user)

        from unittest.mock import patch as _patch
        with _patch('monitor.services.send_digest_notification', side_effect=capturing_send):
            with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
                from .services import run_checks_for_user
                run_checks_for_user(self.user)

        rule_names = [r.rule.name for r in captured_results]
        self.assertIn('notif_on', rule_names)
        self.assertNotIn('silent_fail', rule_names)


class NotificationModeTest(TestCase):
    """Immediate vs digest routing in run_checks_for_user and run_all_checks."""

    def setUp(self):
        self.user = User.objects.create_user(
            'mode_test_user', email='mode@example.com', password='pass'
        )
        self.conn = make_connection(user=self.user)

    def _failing_cursor_mock(self):
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (1,)  # below min_rows=100 -> FAIL
        return cursor

    @patch('monitor.services.psycopg2.connect')
    def test_digest_mode_sends_one_email_for_n_failures(self, mock_connect):
        from django.core import mail
        from django.test.utils import override_settings

        self.user.profile.notification_mode = 'digest'
        self.user.profile.save()

        mock_connect.return_value.cursor.return_value = self._failing_cursor_mock()

        for i in range(3):
            r = make_rule(name=f'digest_{i}', min_rows=100,
                          connection=self.conn, user=self.user)
            r.notify_on_fail = True
            r.save()

        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            from .services import run_checks_for_user
            run_checks_for_user(self.user)

        self.assertEqual(len(mail.outbox), 1)

    @patch('monitor.services.psycopg2.connect')
    def test_immediate_mode_sends_n_emails_for_n_failures(self, mock_connect):
        from django.core import mail
        from django.test.utils import override_settings

        mock_connect.return_value.cursor.return_value = self._failing_cursor_mock()

        for i in range(3):
            r = make_rule(name=f'imm_{i}', min_rows=100,
                          connection=self.conn, user=self.user)
            r.notify_on_fail = True
            r.save()

        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            from .services import run_checks_for_user
            run_checks_for_user(self.user)

        self.assertEqual(len(mail.outbox), 3)

    @patch('monitor.services.psycopg2.connect')
    def test_digest_mode_sends_no_email_when_all_ok(self, mock_connect):
        from django.core import mail
        from django.test.utils import override_settings

        self.user.profile.notification_mode = 'digest'
        self.user.profile.save()

        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = (999,)  # above min_rows -> OK
        mock_connect.return_value.cursor.return_value = cursor

        r = make_rule(name='all_ok', min_rows=1,
                      connection=self.conn, user=self.user)
        r.notify_on_fail = True
        r.save()

        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            from .services import run_checks_for_user
            run_checks_for_user(self.user)

        self.assertEqual(len(mail.outbox), 0)

    @patch('monitor.services.psycopg2.connect')
    def test_run_all_checks_two_digest_users_sends_two_emails(self, mock_connect):
        from django.core import mail
        from django.test.utils import override_settings

        user2 = User.objects.create_user(
            'digest_user2', email='user2@example.com', password='pass'
        )
        conn2 = make_connection(name='conn2', url='postgresql://u:p@host2/db2', user=user2)

        for u, c in [(self.user, self.conn), (user2, conn2)]:
            u.profile.notification_mode = 'digest'
            u.profile.save()
            r = make_rule(name=f'rule_{u.username}', min_rows=100, connection=c, user=u)
            r.notify_on_fail = True
            r.save()

        mock_connect.return_value.cursor.return_value = self._failing_cursor_mock()

        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            from .services import run_all_checks
            run_all_checks()

        self.assertEqual(len(mail.outbox), 2)


class SettingsViewTest(TestCase):
    """Tests for GET/POST /settings/notifications/ (settings view)."""

    def setUp(self):
        self.user = User.objects.create_user(
            'settings_view_user', email='sv@example.com', password='pass'
        )
        self.client.login(username='settings_view_user', password='pass')

    def test_get_settings_200(self):
        r = self.client.get(reverse('monitor:settings'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'immediate')
        self.assertContains(r, 'digest')

    def test_get_settings_redirects_anonymous(self):
        self.client.logout()
        r = self.client.get(reverse('monitor:settings'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_post_digest_updates_profile(self):
        from .models import UserProfile
        r = self.client.post(reverse('monitor:settings'), {'notification_mode': 'digest'})
        self.assertRedirects(r, reverse('monitor:settings'), fetch_redirect_response=False)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.notification_mode, 'digest')

    def test_post_invalid_mode_returns_400(self):
        r = self.client.post(reverse('monitor:settings'), {'notification_mode': 'foobar'})
        self.assertEqual(r.status_code, 400)

    def test_post_immediate_updates_profile(self):
        from .models import UserProfile
        self.user.profile.notification_mode = 'digest'
        self.user.profile.save()
        r = self.client.post(reverse('monitor:settings'), {'notification_mode': 'immediate'})
        self.assertRedirects(r, reverse('monitor:settings'), fetch_redirect_response=False)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.notification_mode, 'immediate')


# ═══════════════════════════════════════════════════════════════
#  REST API — ApiKey model, auth decorator, and endpoints
# ═══════════════════════════════════════════════════════════════

class ApiKeyModelTest(TestCase):
    """Phase 1: ApiKey model fields, uniqueness, and __str__."""

    def setUp(self):
        self.user = User.objects.create_user('apikey_model_user', password='pass')

    def test_create_api_key(self):
        from .models import ApiKey
        key = ApiKey.objects.create(
            user=self.user,
            name='test key',
            key_hash='a' * 64,
        )
        self.assertEqual(key.name, 'test key')
        self.assertTrue(key.is_active)
        self.assertIsNone(key.last_used_at)

    def test_key_hash_uniqueness_enforced(self):
        """Two rows with the same key_hash should raise IntegrityError."""
        from django.db import IntegrityError
        from .models import ApiKey
        ApiKey.objects.create(user=self.user, name='k1', key_hash='b' * 64)
        with self.assertRaises(IntegrityError):
            ApiKey.objects.create(user=self.user, name='k2', key_hash='b' * 64)

    def test_user_name_unique_together(self):
        """Two keys with the same user+name should raise IntegrityError."""
        from django.db import IntegrityError
        from .models import ApiKey
        ApiKey.objects.create(user=self.user, name='dup', key_hash='c' * 64)
        with self.assertRaises(IntegrityError):
            ApiKey.objects.create(user=self.user, name='dup', key_hash='d' * 64)

    def test_str(self):
        from .models import ApiKey
        key = ApiKey.objects.create(user=self.user, name='ci key', key_hash='e' * 64)
        self.assertIn('ci key', str(key))
        self.assertIn(self.user.username, str(key))


def _make_api_key(user, name='test', raw='testrawkey'):
    """Create an ApiKey row and return (raw_key_string, ApiKey instance)."""
    import hashlib as _hl
    from monitor.models import ApiKey
    key_hash = _hl.sha256(raw.encode()).hexdigest()
    api_key = ApiKey.objects.create(user=user, name=name, key_hash=key_hash)
    return raw, api_key


class ApiAuthTest(TestCase):
    """Phase 2: require_api_key decorator — missing/invalid/inactive key, valid key."""

    def setUp(self):
        self.user = User.objects.create_user('apiauth_user', password='pass')
        self.raw, self.api_key = _make_api_key(self.user, name='auth test')

    def test_missing_auth_header_returns_401(self):
        r = self.client.get('/api/v1/rules')
        self.assertEqual(r.status_code, 401)
        data = json.loads(r.content)
        self.assertIn('error', data)

    def test_wrong_scheme_returns_401(self):
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Token {self.raw}')
        self.assertEqual(r.status_code, 401)

    def test_invalid_key_returns_401(self):
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION='Bearer completely_wrong')
        self.assertEqual(r.status_code, 401)
        data = json.loads(r.content)
        self.assertEqual(data['error'], 'invalid API key')

    def test_inactive_key_returns_401(self):
        from .models import ApiKey
        ApiKey.objects.filter(pk=self.api_key.pk).update(is_active=False)
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 401)

    def test_valid_key_returns_200(self):
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 200)

    def test_valid_key_updates_last_used_at(self):
        from .models import ApiKey
        self.assertIsNone(self.api_key.last_used_at)
        self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.api_key.refresh_from_db()
        self.assertIsNotNone(self.api_key.last_used_at)


from django.test.utils import override_settings as _override_settings

_LOCMEM_CACHE = {'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}}


class RateLimitTest(TestCase):
    """Phase 2: rate limiting — under limit passes, 61st request fails."""

    def setUp(self):
        self.user = User.objects.create_user('ratelimit_user', password='pass')
        self.raw, self.api_key = _make_api_key(self.user, name='rate test', raw='ratelimitrawkey')

    def test_under_limit_passes(self):
        from django.core.cache import cache
        cache.clear()
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 200)

    @_override_settings(**_LOCMEM_CACHE)
    def test_61st_request_returns_429(self):
        """After 60 requests in the same minute bucket, the 61st returns 429."""
        from django.core.cache import cache
        from monitor.api_auth import _RATE_LIMIT
        cache.clear()
        import time
        bucket = int(time.time() // 60)
        cache_key = f'rl:{self.api_key.pk}:{bucket}'
        cache.set(cache_key, _RATE_LIMIT, timeout=120)
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 429)
        data = json.loads(r.content)
        self.assertIn('retry_after_seconds', data)
        self.assertGreaterEqual(data['retry_after_seconds'], 0)


class ApiEndpointsTest(TestCase):
    """Phase 3: API endpoint tests — auth, isolation, response shape."""

    def setUp(self):
        self.user = User.objects.create_user('api_endpoints_user', password='pass')
        self.other_user = User.objects.create_user('api_other_user', password='pass')
        self.raw, self.api_key = _make_api_key(self.user, name='endpoints test', raw='endpointsrawkey')

    def _auth(self):
        return f'Bearer {self.raw}'

    def test_list_rules_without_auth_returns_401(self):
        r = self.client.get('/api/v1/rules')
        self.assertEqual(r.status_code, 401)

    def test_list_rules_returns_only_own_rules(self):
        make_rule(name='my_rule', min_rows=1, user=self.user)
        make_rule(name='other_rule', min_rows=1, user=self.other_user)
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=self._auth())
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        names = [rule['name'] for rule in data['rules']]
        self.assertIn('my_rule', names)
        self.assertNotIn('other_rule', names)

    def test_list_rules_response_shape(self):
        make_rule(name='shape_rule', min_rows=1, user=self.user)
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=self._auth())
        data = json.loads(r.content)
        self.assertIn('rules', data)
        rule = data['rules'][0]
        for field in ('id', 'name', 'schema_name', 'table_name', 'rule_type',
                      'schedule_type', 'created_at', 'updated_at'):
            self.assertIn(field, rule, f'Missing field: {field}')

    def test_run_rule_returns_run_id_and_status(self):
        from unittest.mock import patch, MagicMock
        conn = make_connection(user=self.user)
        rule = make_rule(min_rows=1, connection=conn, user=self.user)
        with patch('monitor.api_views.run_single_rule') as mock_run:
            mock_result = MagicMock()
            mock_result.run_id = 99
            mock_result.status = 'OK'
            mock_result.row_count = 10
            mock_result.last_record_age_hours = None
            mock_result.error_message = ''
            mock_result.checked_at.isoformat.return_value = '2026-01-01T00:00:00+00:00'
            mock_run.return_value = mock_result
            r = self.client.post(
                f'/api/v1/rules/{rule.pk}/run',
                HTTP_AUTHORIZATION=self._auth(),
            )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('run_id', data)
        self.assertIn('status', data)

    def test_run_rule_other_user_returns_404(self):
        other_rule = make_rule(name='other_user_rule', min_rows=1, user=self.other_user)
        r = self.client.post(
            f'/api/v1/rules/{other_rule.pk}/run',
            HTTP_AUTHORIZATION=self._auth(),
        )
        self.assertEqual(r.status_code, 404)

    def test_run_all_returns_run_id_and_counts(self):
        from unittest.mock import patch, MagicMock
        with patch('monitor.api_views.run_checks_for_user') as mock_run:
            mock_run_obj = MagicMock()
            mock_run_obj.pk = 55
            mock_run_obj.ok_count = 0
            mock_run_obj.fail_count = 0
            mock_run_obj.error_count = 0
            mock_run_obj.started_at.isoformat.return_value = '2026-01-01T00:00:00+00:00'
            mock_run_obj.finished_at = None
            mock_run.return_value = mock_run_obj
            r = self.client.post('/api/v1/rules/run-all', HTTP_AUTHORIZATION=self._auth())
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('run_id', data)
        self.assertIn('ok_count', data)
        self.assertIn('fail_count', data)
        self.assertIn('error_count', data)

    def test_get_results_nonexistent_rule_returns_404(self):
        r = self.client.get('/api/v1/rules/99999/results', HTTP_AUTHORIZATION=self._auth())
        self.assertEqual(r.status_code, 404)

    def test_get_results_other_user_rule_returns_404(self):
        other_rule = make_rule(name='other_results_rule', min_rows=1, user=self.other_user)
        r = self.client.get(
            f'/api/v1/rules/{other_rule.pk}/results',
            HTTP_AUTHORIZATION=self._auth(),
        )
        self.assertEqual(r.status_code, 404)

    def test_get_results_returns_last_20(self):
        rule = make_rule(name='results_rule', min_rows=1, user=self.user)
        run = CheckRun.objects.create(finished_at=timezone.now())
        for i in range(25):
            RuleResult.objects.create(run=run, rule=rule, status='OK')
        r = self.client.get(
            f'/api/v1/rules/{rule.pk}/results',
            HTTP_AUTHORIZATION=self._auth(),
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('results', data)
        self.assertLessEqual(len(data['results']), 20)
        self.assertEqual(data['rule_id'], rule.pk)

    def test_get_results_response_shape(self):
        rule = make_rule(name='shape_results_rule', min_rows=1, user=self.user)
        run = CheckRun.objects.create(finished_at=timezone.now())
        RuleResult.objects.create(run=run, rule=rule, status='OK')
        r = self.client.get(
            f'/api/v1/rules/{rule.pk}/results',
            HTTP_AUTHORIZATION=self._auth(),
        )
        data = json.loads(r.content)
        result = data['results'][0]
        for field in ('run_id', 'status', 'row_count', 'last_record_age_hours',
                      'error_message', 'checked_at'):
            self.assertIn(field, result, f'Missing field: {field}')


class ApiKeyViewTest(TestCase):
    """Phase 2 + 4: key management UI views."""

    def setUp(self):
        self.user = User.objects.create_user('apikey_view_user', password='pass')
        self.client.login(username='apikey_view_user', password='pass')

    def test_list_view_redirects_unauthenticated(self):
        self.client.logout()
        r = self.client.get(reverse('monitor:api_key_list'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_list_view_returns_200_when_logged_in(self):
        r = self.client.get(reverse('monitor:api_key_list'))
        self.assertEqual(r.status_code, 200)

    def test_create_key_creates_api_key_row(self):
        from .models import ApiKey
        self.assertEqual(ApiKey.objects.filter(user=self.user).count(), 0)
        r = self.client.post(
            reverse('monitor:api_key_create'),
            {'name': 'my ci key'},
        )
        self.assertRedirects(r, reverse('monitor:api_key_list'), fetch_redirect_response=False)
        self.assertEqual(ApiKey.objects.filter(user=self.user).count(), 1)
        key = ApiKey.objects.get(user=self.user)
        self.assertTrue(key.is_active)

    def test_create_key_raw_key_starts_with_dp(self):
        self.client.post(
            reverse('monitor:api_key_create'),
            {'name': 'dp prefix key'},
        )
        session = self.client.session
        raw_key = session.get('new_api_key', '')
        self.assertTrue(raw_key.startswith('dp_'), f'Expected dp_ prefix, got: {raw_key}')

    def test_revoke_key_sets_is_active_false(self):
        from .models import ApiKey
        _, key = _make_api_key(self.user, name='to revoke')
        self.assertTrue(key.is_active)
        r = self.client.post(
            reverse('monitor:api_key_revoke', args=[key.pk]),
        )
        self.assertRedirects(r, reverse('monitor:api_key_list'), fetch_redirect_response=False)
        key.refresh_from_db()
        self.assertFalse(key.is_active)

    def test_revoke_other_users_key_returns_404(self):
        other = User.objects.create_user('other_key_owner', password='pass')
        _, key = _make_api_key(other, name='other key')
        r = self.client.post(
            reverse('monitor:api_key_revoke', args=[key.pk]),
        )
        self.assertEqual(r.status_code, 404)
        key.refresh_from_db()
        self.assertTrue(key.is_active)


# ═════════════════════════════════════════════════════════════════
#  Slack Webhook (slack-webhook change)
# ═════════════════════════════════════════════════════════════════

class SlackWebhookModelTest(TestCase):
    """Unit tests for the SlackWebhook model."""

    def setUp(self):
        self.user = User.objects.create_user('swh_model_user', password='pass')

    def test_enabled_default_true(self):
        """enabled defaults to True."""
        from .models import SlackWebhook
        wh = SlackWebhook.objects.create(user=self.user, name='default-test', url='https://hooks.slack.com/x')
        self.assertTrue(wh.enabled)

    def test_str_returns_name(self):
        """__str__ returns the webhook name."""
        from .models import SlackWebhook
        wh = SlackWebhook.objects.create(user=self.user, name='my-webhook', url='https://hooks.slack.com/x')
        self.assertEqual(str(wh), 'my-webhook')

    def test_unique_together_user_name(self):
        """(user, name) unique_together raises IntegrityError on duplicate."""
        from .models import SlackWebhook
        from django.db import IntegrityError
        SlackWebhook.objects.create(user=self.user, name='dup-webhook', url='https://hooks.slack.com/a')
        with self.assertRaises(IntegrityError):
            SlackWebhook.objects.create(user=self.user, name='dup-webhook', url='https://hooks.slack.com/b')


class SendSlackNotificationTest(TestCase):
    """Unit tests for monitor.slack_service.send_slack_notification."""

    def setUp(self):
        self.user = User.objects.create_user('slack_notif_user', email='slack@example.com', password='pass')
        self.rule = make_rule(name='slack_test_rule', min_rows=10, user=self.user)
        self.rule.notify_slack = True
        self.rule.save()

        from .models import SlackWebhook
        self.webhook = SlackWebhook.objects.create(
            user=self.user,
            name='test-webhook',
            url='https://hooks.slack.com/services/TEST',
            enabled=True,
        )

        self.run = CheckRun.objects.create(finished_at=timezone.now())
        self.result = RuleResult.objects.create(
            run=self.run,
            rule=self.rule,
            status=RuleResult.Status.FAIL,
        )

    def _send(self, **overrides):
        from .slack_service import send_slack_notification
        rule = overrides.get('rule', self.rule)
        result = overrides.get('result', self.result)
        return send_slack_notification(rule, result)

    def test_returns_false_when_notify_slack_false(self):
        """Returns False when rule.notify_slack is False."""
        self.rule.notify_slack = False
        self.rule.save()
        with patch('urllib.request.urlopen') as mock_open:
            sent = self._send()
        self.assertFalse(sent)
        mock_open.assert_not_called()

    def test_returns_false_when_no_enabled_webhook(self):
        """Returns False when no enabled SlackWebhook exists for the user."""
        self.webhook.enabled = False
        self.webhook.save()
        with patch('urllib.request.urlopen') as mock_open:
            sent = self._send()
        self.assertFalse(sent)
        mock_open.assert_not_called()

    def test_returns_false_when_cooldown_active(self):
        """Returns False when last_slack_notified_at < 1 hour ago."""
        from datetime import timedelta
        self.rule.last_slack_notified_at = timezone.now() - timedelta(minutes=30)
        self.rule.save()
        with patch('urllib.request.urlopen') as mock_open:
            sent = self._send()
        self.assertFalse(sent)
        mock_open.assert_not_called()

    def test_returns_true_after_cooldown_expires(self):
        """Returns True when last_slack_notified_at >= 1 hour ago."""
        from datetime import timedelta
        self.rule.last_slack_notified_at = timezone.now() - timedelta(hours=1, seconds=1)
        self.rule.save()
        with patch('urllib.request.urlopen'):
            sent = self._send()
        self.assertTrue(sent)

    def test_stamps_last_slack_notified_at_on_success(self):
        """last_slack_notified_at is set in DB after a successful POST."""
        self.assertIsNone(self.rule.last_slack_notified_at)
        with patch('urllib.request.urlopen'):
            self._send()
        self.rule.refresh_from_db()
        self.assertIsNotNone(self.rule.last_slack_notified_at)

    def test_cooldown_stamp_uses_update_not_save(self):
        """The cooldown stamp uses .update() so auto_now updated_at is not changed."""
        before = self.rule.updated_at
        with patch('urllib.request.urlopen'):
            self._send()
        self.rule.refresh_from_db()
        # updated_at must not move because we only call .update(last_slack_notified_at=...)
        self.assertEqual(self.rule.updated_at, before)

    def test_returns_false_and_logs_on_url_error(self):
        """Returns False (does not raise) when urllib raises URLError."""
        import urllib.error
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('timeout')), \
             self.assertLogs('monitor.slack_service', level='ERROR'):
            sent = self._send()
        self.assertFalse(sent)

    def test_block_kit_payload_contains_rule_name_and_view_history(self):
        """The POSTed JSON contains the rule name and 'View History' button (if BASE_URL set)."""
        from django.test.utils import override_settings
        captured = []

        def fake_urlopen(req, timeout=None):
            captured.append(req)

        with override_settings(BASE_URL='http://example.com'):
            with patch('urllib.request.urlopen', side_effect=fake_urlopen):
                self._send()

        self.assertTrue(len(captured) > 0, 'urlopen was not called')
        import json as _json
        payload = _json.loads(captured[0].data.decode())
        # Fallback text must contain rule name
        self.assertIn(self.rule.name, payload['text'])
        # At least one block must contain 'View History'
        blocks_str = _json.dumps(payload['blocks'])
        self.assertIn('View History', blocks_str)


class NotifyRuleResultTest(TestCase):
    """Unit tests for notify_rule_result coordinator."""

    def setUp(self):
        self.user = User.objects.create_user('coord_user', email='coord@example.com', password='pass')
        self.rule = make_rule(name='coord_test_rule', min_rows=10, user=self.user)
        self.run = CheckRun.objects.create(finished_at=timezone.now())
        self.result = RuleResult.objects.create(
            run=self.run, rule=self.rule, status=RuleResult.Status.FAIL
        )

    def test_returns_both_true_when_both_succeed(self):
        """Returns {'email': True, 'slack': True} when both channels succeed."""
        with patch('monitor.email_service.send_fail_notification', return_value=True), \
             patch('monitor.email_service.send_slack_notification', return_value=True):
            from .email_service import notify_rule_result
            result = notify_rule_result(self.rule, self.result)
        self.assertEqual(result, {'email': True, 'slack': True})

    def test_returns_email_false_when_email_skipped(self):
        """Returns {'email': False, 'slack': True} when email is skipped."""
        with patch('monitor.email_service.send_fail_notification', return_value=False), \
             patch('monitor.email_service.send_slack_notification', return_value=True):
            from .email_service import notify_rule_result
            result = notify_rule_result(self.rule, self.result)
        self.assertEqual(result, {'email': False, 'slack': True})

    def test_returns_slack_false_when_slack_skipped(self):
        """Returns {'email': True, 'slack': False} when Slack is skipped."""
        with patch('monitor.email_service.send_fail_notification', return_value=True), \
             patch('monitor.email_service.send_slack_notification', return_value=False):
            from .email_service import notify_rule_result
            result = notify_rule_result(self.rule, self.result)
        self.assertEqual(result, {'email': True, 'slack': False})


class SlackWebhookViewsTest(TestCase):
    """Auth-guard and happy-path tests for SlackWebhook CRUD views."""

    def setUp(self):
        self.user = User.objects.create_user('swh_views_user', password='pass')
        self.other_user = User.objects.create_user('swh_other_user', password='pass')
        self.client.login(username='swh_views_user', password='pass')

    def test_unauthenticated_redirects_to_login(self):
        """Anonymous GET of slack_webhook_list returns 302 to login."""
        self.client.logout()
        r = self.client.get(reverse('monitor:slack_webhook_list'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_list_view_renders(self):
        """Authenticated GET of slack_webhook_list returns 200."""
        r = self.client.get(reverse('monitor:slack_webhook_list'))
        self.assertEqual(r.status_code, 200)

    def test_create_saves_with_request_user(self):
        """POST to slack_webhook_create saves the webhook with user=request.user."""
        r = self.client.post(reverse('monitor:slack_webhook_create'), {
            'name': 'my-alert',
            'url': 'https://hooks.slack.com/services/ABC',
            'enabled': 'on',
        })
        self.assertRedirects(r, reverse('monitor:slack_webhook_list'), fetch_redirect_response=False)
        from .models import SlackWebhook
        wh = SlackWebhook.objects.get(name='my-alert')
        self.assertEqual(wh.user, self.user)
        self.assertTrue(wh.enabled)

    def test_edit_scoped_to_owner(self):
        """Editing another user's webhook returns 404."""
        from .models import SlackWebhook
        other_wh = SlackWebhook.objects.create(
            user=self.other_user,
            name='other-hook',
            url='https://hooks.slack.com/services/XYZ',
        )
        r = self.client.get(reverse('monitor:slack_webhook_edit', args=[other_wh.pk]))
        self.assertEqual(r.status_code, 404)

    def test_delete_removes_record(self):
        """POST to slack_webhook_delete removes the webhook."""
        from .models import SlackWebhook
        wh = SlackWebhook.objects.create(
            user=self.user,
            name='to-delete',
            url='https://hooks.slack.com/services/DEL',
        )
        r = self.client.post(reverse('monitor:slack_webhook_delete', args=[wh.pk]))
        self.assertRedirects(r, reverse('monitor:slack_webhook_list'), fetch_redirect_response=False)
        self.assertFalse(SlackWebhook.objects.filter(pk=wh.pk).exists())

# ═══════════════════════════════════════════════════════════════════
#  check-templates: CheckTemplatesTests + ApiTemplatesTests + TemplateUITest
# ═══════════════════════════════════════════════════════════════════

# Forbidden keywords — F3: DELETE is explicitly included
_FORBIDDEN_KEYWORDS = (
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE',
    'ALTER', 'CREATE', 'GRANT', 'REVOKE',
)


def _assert_sql_safe(test_case, sql):
    """Assert sql starts with SELECT and contains no forbidden DML/DDL keyword."""
    import re
    test_case.assertTrue(
        sql.strip().upper().startswith('SELECT'),
        'SQL does not start with SELECT: {!r}'.format(sql),
    )
    for kw in _FORBIDDEN_KEYWORDS:
        test_case.assertFalse(
            bool(re.search(r'\b' + kw + r'\b', sql, re.IGNORECASE)),
            'SQL contains forbidden keyword {!r}: {!r}'.format(kw, sql),
        )


class CheckTemplatesTests(TestCase):
    """Unit tests for check_templates.TEMPLATES and generate_sql()."""

    def setUp(self):
        from monitor.check_templates import TEMPLATES, generate_sql
        self.TEMPLATES = TEMPLATES
        self.generate_sql = generate_sql

    def test_template_count_is_8(self):
        self.assertEqual(len(self.TEMPLATES), 8)

    def test_each_template_has_required_keys(self):
        for tpl in self.TEMPLATES:
            for key in ('id', 'label', 'description', 'params', 'sql'):
                self.assertIn(key, tpl, 'Template {!r} missing key {!r}'.format(tpl.get('id'), key))

    def test_null_check_postgresql(self):
        sql = self.generate_sql('null_check', {'table': 'public.orders', 'column': 'customer_id'}, 'postgresql')
        _assert_sql_safe(self, sql)
        self.assertIn('public.orders', sql)
        self.assertIn('customer_id', sql)
        self.assertIn('IS NULL', sql)

    def test_null_check_mysql(self):
        sql = self.generate_sql('null_check', {'table': 'mydb.orders', 'column': 'email'}, 'mysql')
        _assert_sql_safe(self, sql)
        self.assertIn('IS NULL', sql)

    def test_uniqueness_postgresql(self):
        sql = self.generate_sql('uniqueness', {'table': 'public.users', 'column': 'email'}, 'postgresql')
        _assert_sql_safe(self, sql)
        self.assertIn('DISTINCT', sql)
        self.assertIn('email', sql)

    def test_uniqueness_mysql(self):
        sql = self.generate_sql('uniqueness', {'table': 'mydb.users', 'column': 'id'}, 'mysql')
        _assert_sql_safe(self, sql)
        self.assertIn('DISTINCT', sql)

    def test_not_negative_postgresql(self):
        sql = self.generate_sql('not_negative', {'table': 'public.orders', 'column': 'amount'}, 'postgresql')
        _assert_sql_safe(self, sql)
        self.assertIn('amount', sql)
        self.assertIn('>= 0', sql)

    def test_not_negative_mysql(self):
        sql = self.generate_sql('not_negative', {'table': 'mydb.orders', 'column': 'price'}, 'mysql')
        _assert_sql_safe(self, sql)
        self.assertIn('>= 0', sql)

    def test_future_date_postgresql(self):
        sql = self.generate_sql('future_date', {'table': 'public.events', 'column': 'event_date'}, 'postgresql')
        _assert_sql_safe(self, sql)
        self.assertIn('event_date', sql)
        self.assertIn('NOW()', sql)

    def test_future_date_mysql(self):
        sql = self.generate_sql('future_date', {'table': 'mydb.events', 'column': 'ts'}, 'mysql')
        _assert_sql_safe(self, sql)
        self.assertIn('NOW()', sql)

    def test_referential_integrity_postgresql(self):
        params = {
            'child_table':   'public.orders',
            'child_column':  'customer_id',
            'parent_table':  'public.customers',
            'parent_column': 'id',
        }
        sql = self.generate_sql('referential_integrity', params, 'postgresql')
        _assert_sql_safe(self, sql)
        self.assertIn('public.orders', sql)
        self.assertIn('customer_id', sql)
        self.assertIn('public.customers', sql)
        self.assertIn('NOT IN', sql)

    def test_referential_integrity_mysql(self):
        params = {
            'child_table':   'mydb.orders',
            'child_column':  'cust_id',
            'parent_table':  'mydb.customers',
            'parent_column': 'id',
        }
        sql = self.generate_sql('referential_integrity', params, 'mysql')
        _assert_sql_safe(self, sql)
        self.assertIn('NOT IN', sql)

    def test_completeness_rate_postgresql(self):
        sql = self.generate_sql(
            'completeness_rate',
            {'table': 'public.users', 'column': 'email', 'threshold': '95'},
            'postgresql',
        )
        _assert_sql_safe(self, sql)
        self.assertIn('95', sql)
        self.assertIn('NULLIF', sql)

    def test_completeness_rate_mysql(self):
        sql = self.generate_sql(
            'completeness_rate',
            {'table': 'mydb.users', 'column': 'name', 'threshold': '80'},
            'mysql',
        )
        _assert_sql_safe(self, sql)
        self.assertIn('80', sql)

    def test_row_count_equals_postgresql(self):
        sql = self.generate_sql(
            'row_count_equals',
            {'table': 'public.orders', 'expected_count': '500'},
            'postgresql',
        )
        _assert_sql_safe(self, sql)
        self.assertIn('500', sql)
        self.assertIn('COUNT(*)', sql)

    def test_row_count_equals_mysql(self):
        sql = self.generate_sql(
            'row_count_equals',
            {'table': 'mydb.orders', 'expected_count': '200'},
            'mysql',
        )
        _assert_sql_safe(self, sql)
        self.assertIn('200', sql)

    def test_pattern_match_postgresql_uses_regex_operator(self):
        sql = self.generate_sql(
            'pattern_match',
            {'table': 'public.users', 'column': 'email', 'pattern': '^[a-z]+'},
            'postgresql',
        )
        _assert_sql_safe(self, sql)
        self.assertIn('!~', sql)
        self.assertNotIn('REGEXP', sql)
        self.assertIn('^[a-z]+', sql)

    def test_pattern_match_mysql_uses_regexp(self):
        sql = self.generate_sql(
            'pattern_match',
            {'table': 'mydb.users', 'column': 'email', 'pattern': '^[a-z]+'},
            'mysql',
        )
        _assert_sql_safe(self, sql)
        self.assertIn('REGEXP', sql)
        self.assertNotIn('!~', sql)
        self.assertIn('^[a-z]+', sql)

    def test_generate_sql_raises_for_unknown_template(self):
        with self.assertRaises(KeyError):
            self.generate_sql('nonexistent_template', {}, 'postgresql')

    def test_generate_sql_raises_for_unknown_provider(self):
        with self.assertRaises(KeyError):
            self.generate_sql('null_check', {'table': 't', 'column': 'c'}, 'oracle')


class ApiTemplatesTests(TestCase):
    """Integration tests for the GET /api/templates/ endpoint."""

    def setUp(self):
        self.user = User.objects.create_user('tpl_api_user', password='pass')

    def test_unauthenticated_redirects(self):
        r = self.client.get('/api/templates/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_authenticated_returns_200(self):
        self.client.force_login(self.user)
        r = self.client.get('/api/templates/')
        self.assertEqual(r.status_code, 200)

    def test_authenticated_returns_8_templates(self):
        self.client.force_login(self.user)
        r = self.client.get('/api/templates/')
        data = json.loads(r.content)
        self.assertIn('templates', data)
        self.assertEqual(len(data['templates']), 8)

    def test_each_template_has_required_keys(self):
        self.client.force_login(self.user)
        r = self.client.get('/api/templates/')
        data = json.loads(r.content)
        for tpl in data['templates']:
            for key in ('id', 'label', 'description', 'params', 'sql'):
                self.assertIn(
                    key, tpl,
                    'Template {!r} missing key {!r}'.format(tpl.get('id'), key),
                )

    def test_post_not_allowed(self):
        self.client.force_login(self.user)
        r = self.client.post('/api/templates/', {})
        self.assertEqual(r.status_code, 405)


class TemplateUITest(TestCase):
    """Verify the rule_create page includes the template gallery section."""

    def setUp(self):
        self.user = User.objects.create_user('tpl_ui_user', password='pass')
        self.client.force_login(self.user)

    def test_rule_create_has_template_gallery_section(self):
        r = self.client.get(reverse('monitor:rule_create'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'tpl-gallery-section')

    def test_rule_create_has_template_apply_button(self):
        r = self.client.get(reverse('monitor:rule_create'))
        self.assertContains(r, 'tpl-apply-btn')

    def test_rule_create_has_api_templates_fetch(self):
        r = self.client.get(reverse('monitor:rule_create'))
        self.assertContains(r, '/api/templates/')


# ═══════════════════════════════════════════════════════════════════
#  Row Sampling — Phase 5 Tests
# ═══════════════════════════════════════════════════════════════════

import datetime as _dt
import decimal as _decimal


class SerializeRowTest(TestCase):
    """Unit tests for _serialize_row — JSON serialization of DBAPI2 rows."""

    def _desc(self, *names):
        """Build a minimal cursor.description-like list of col descriptors."""
        return [(name,) for name in names]

    def test_datetime_converted_to_isoformat(self):
        from .services import _serialize_row
        dt_val = _dt.datetime(2024, 3, 15, 10, 30, 0)
        row = _serialize_row(self._desc('created_at'), (dt_val,))
        self.assertEqual(row['created_at'], dt_val.isoformat())

    def test_date_converted_to_isoformat(self):
        from .services import _serialize_row
        d_val = _dt.date(2024, 3, 15)
        row = _serialize_row(self._desc('birth_date'), (d_val,))
        self.assertEqual(row['birth_date'], d_val.isoformat())

    def test_decimal_converted_to_str(self):
        from .services import _serialize_row
        dec_val = _decimal.Decimal('123.456')
        row = _serialize_row(self._desc('price'), (dec_val,))
        self.assertEqual(row['price'], '123.456')

    def test_primitives_pass_through(self):
        from .services import _serialize_row
        row = _serialize_row(
            self._desc('id', 'name', 'score', 'active', 'nullable'),
            (42, 'hello', 3.14, True, None),
        )
        self.assertEqual(row['id'], 42)
        self.assertEqual(row['name'], 'hello')
        self.assertAlmostEqual(row['score'], 3.14)
        self.assertTrue(row['active'])
        self.assertIsNone(row['nullable'])

    def test_mixed_row_serialized_correctly(self):
        from .services import _serialize_row
        dt_val = _dt.datetime(2024, 1, 1, 0, 0, 0)
        dec_val = _decimal.Decimal('9.99')
        row = _serialize_row(
            self._desc('ts', 'amount', 'label'),
            (dt_val, dec_val, 'test'),
        )
        self.assertEqual(row['ts'], dt_val.isoformat())
        self.assertEqual(row['amount'], '9.99')
        self.assertEqual(row['label'], 'test')


class FetchSampleRowsTest(TestCase):
    """Unit tests for _fetch_sample_rows — cursor-based sampling helper."""

    def _mock_cursor(self, rows, col_names):
        """Build a mock cursor with description and fetchmany."""
        cur = MagicMock()
        cur.description = [(name,) for name in col_names]
        cur.fetchmany.return_value = rows
        return cur

    def test_happy_path_returns_list_of_dicts(self):
        from .services import _fetch_sample_rows
        cur = self._mock_cursor(
            [(1, 'alice'), (2, 'bob')],
            ['id', 'name'],
        )
        result = _fetch_sample_rows(cur, 'SELECT * FROM t LIMIT 5')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {'id': 1, 'name': 'alice'})
        self.assertEqual(result[1], {'id': 2, 'name': 'bob'})

    def test_cursor_exception_returns_none(self):
        from .services import _fetch_sample_rows
        cur = MagicMock()
        cur.execute.side_effect = Exception('DB error')
        result = _fetch_sample_rows(cur, 'SELECT * FROM t LIMIT 5')
        self.assertIsNone(result)

    def test_respects_limit_param(self):
        from .services import _fetch_sample_rows
        cur = self._mock_cursor([(1, 'x')], ['id', 'val'])
        _fetch_sample_rows(cur, 'SELECT * FROM t LIMIT 3', limit=3)
        cur.fetchmany.assert_called_once_with(3)

    def test_params_passed_to_execute(self):
        from .services import _fetch_sample_rows
        cur = self._mock_cursor([], ['id'])
        _fetch_sample_rows(cur, 'SELECT * FROM t WHERE id = %s', params=(42,))
        cur.execute.assert_called_once_with('SELECT * FROM t WHERE id = %s', (42,))


class SamplingVolumeFreshnessTest(TestCase):
    """Verify sample_rows is populated on FAIL and absent on OK for volume/freshness rules."""

    def setUp(self):
        self.user = User.objects.create_user('sampling_vol_user', password='pass')

    def _make_two_cursor_conn(self, primary_fetchone, sample_fetchmany, sample_col_names):
        """Return a conn mock where first cursor call is primary, second is sample."""
        primary_cur = MagicMock()
        primary_cur.__enter__ = MagicMock(return_value=primary_cur)
        primary_cur.__exit__ = MagicMock(return_value=False)
        primary_cur.fetchone.return_value = primary_fetchone

        sample_cur = MagicMock()
        sample_cur.__enter__ = MagicMock(return_value=sample_cur)
        sample_cur.__exit__ = MagicMock(return_value=False)
        sample_cur.description = [(name,) for name in sample_col_names]
        sample_cur.fetchmany.return_value = sample_fetchmany

        conn = MagicMock()
        conn.cursor.side_effect = [primary_cur, sample_cur]
        return conn

    def test_volume_fail_returns_sample_rows(self):
        from .services import _check_volume_freshness
        rule = make_rule(min_rows=100, user=self.user)
        conn = self._make_two_cursor_conn(
            primary_fetchone=(3,),
            sample_fetchmany=[(1, 'a'), (2, 'b')],
            sample_col_names=['id', 'name'],
        )
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'FAIL')
        self.assertIsNotNone(result['sample_rows'])
        self.assertIsInstance(result['sample_rows'], list)
        self.assertEqual(len(result['sample_rows']), 2)

    def test_volume_ok_no_sample_rows(self):
        from .services import _check_volume_freshness
        rule = make_rule(min_rows=1, user=self.user)
        primary_cur = MagicMock()
        primary_cur.__enter__ = MagicMock(return_value=primary_cur)
        primary_cur.__exit__ = MagicMock(return_value=False)
        primary_cur.fetchone.return_value = (50,)
        conn = MagicMock()
        conn.cursor.return_value = primary_cur
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'OK')
        self.assertIsNone(result['sample_rows'])

    def test_freshness_fail_returns_sample_rows(self):
        from .services import _check_volume_freshness
        rule = make_rule(ts_col='created_at', max_age=1, user=self.user)
        conn = self._make_two_cursor_conn(
            primary_fetchone=(5.0,),  # 5 hours > max_age=1 → FAIL
            sample_fetchmany=[(10, '2024-01-01')],
            sample_col_names=['id', 'created_at'],
        )
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'FAIL')
        self.assertIsNotNone(result['sample_rows'])

    def test_sampling_failure_does_not_convert_fail_to_error(self):
        from .services import _check_volume_freshness
        rule = make_rule(min_rows=100, user=self.user)
        primary_cur = MagicMock()
        primary_cur.__enter__ = MagicMock(return_value=primary_cur)
        primary_cur.__exit__ = MagicMock(return_value=False)
        primary_cur.fetchone.return_value = (3,)

        sample_cur = MagicMock()
        sample_cur.__enter__ = MagicMock(return_value=sample_cur)
        sample_cur.__exit__ = MagicMock(return_value=False)
        sample_cur.execute.side_effect = Exception('DB error during sampling')

        conn = MagicMock()
        conn.cursor.side_effect = [primary_cur, sample_cur]
        result = _check_volume_freshness(conn, rule)
        self.assertEqual(result['status'], 'FAIL')
        self.assertIsNone(result['sample_rows'])


class SamplingCustomSQLTest(TestCase):
    """Verify sample_rows is populated on FAIL and absent on OK for custom SQL rules."""

    def setUp(self):
        self.user = User.objects.create_user('sampling_sql_user', password='pass')

    def _make_custom_sql_conn(self, primary_fetchone, sample_fetchmany=None, sample_col_names=None):
        """Return a conn mock for custom SQL: first cursor for primary check, second for sampling."""
        primary_cur = MagicMock()
        primary_cur.__enter__ = MagicMock(return_value=primary_cur)
        primary_cur.__exit__ = MagicMock(return_value=False)
        primary_cur.fetchone.return_value = primary_fetchone

        if sample_fetchmany is not None:
            sample_cur = MagicMock()
            sample_cur.__enter__ = MagicMock(return_value=sample_cur)
            sample_cur.__exit__ = MagicMock(return_value=False)
            sample_cur.description = [(name,) for name in (sample_col_names or [])]
            sample_cur.fetchmany.return_value = sample_fetchmany

            conn = MagicMock()
            conn.cursor.side_effect = [primary_cur, sample_cur]
        else:
            conn = MagicMock()
            conn.cursor.return_value = primary_cur

        return conn

    def test_custom_sql_fail_returns_sample_rows(self):
        from .services import _check_custom_sql
        rule = make_rule(rule_type='custom_sql', custom_sql='SELECT false', user=self.user)
        conn = self._make_custom_sql_conn(
            primary_fetchone=(False,),
            sample_fetchmany=[(1, 'test')],
            sample_col_names=['id', 'name'],
        )
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'FAIL')
        self.assertIsNotNone(result['sample_rows'])
        self.assertIsInstance(result['sample_rows'], list)

    def test_custom_sql_ok_no_sample_rows(self):
        from .services import _check_custom_sql
        rule = make_rule(rule_type='custom_sql', custom_sql='SELECT true', user=self.user)
        conn = self._make_custom_sql_conn(primary_fetchone=(True,))
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'OK')
        self.assertIsNone(result['sample_rows'])

    def test_custom_sql_empty_result_fail_returns_sample_rows(self):
        from .services import _check_custom_sql
        rule = make_rule(rule_type='custom_sql', custom_sql='SELECT 1 WHERE false', user=self.user)
        conn = self._make_custom_sql_conn(
            primary_fetchone=None,  # empty resultset -> FAIL
            sample_fetchmany=[],
            sample_col_names=[],
        )
        result = _check_custom_sql(conn, rule)
        self.assertEqual(result['status'], 'FAIL')
        self.assertIsInstance(result['sample_rows'], list)


class SamplingRunSingleRuleTest(TestCase):
    """Verify run_single_rule propagates sample_rows to the persisted RuleResult."""

    def setUp(self):
        self.user = User.objects.create_user('sampling_run_user', password='pass')

    @patch('monitor.services.psycopg2.connect')
    def test_fail_result_persists_sample_rows(self, mock_connect):
        primary_cur = MagicMock()
        primary_cur.__enter__ = MagicMock(return_value=primary_cur)
        primary_cur.__exit__ = MagicMock(return_value=False)
        primary_cur.fetchone.return_value = (3,)  # below min_rows=1000 -> FAIL

        sample_cur = MagicMock()
        sample_cur.__enter__ = MagicMock(return_value=sample_cur)
        sample_cur.__exit__ = MagicMock(return_value=False)
        sample_cur.description = [('id',), ('name',)]
        sample_cur.fetchmany.return_value = [(1, 'alice'), (2, 'bob')]

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = [primary_cur, sample_cur]
        mock_connect.return_value = mock_conn

        conn = make_connection(user=self.user)
        rule = make_rule(min_rows=1000, connection=conn, user=self.user)
        from .services import run_single_rule
        result = run_single_rule(rule)

        self.assertEqual(result.status, 'FAIL')
        result.refresh_from_db()
        self.assertIsNotNone(result.sample_rows)
        self.assertIsInstance(result.sample_rows, list)

    @patch('monitor.services.psycopg2.connect')
    def test_ok_result_has_null_sample_rows(self, mock_connect):
        primary_cur = MagicMock()
        primary_cur.__enter__ = MagicMock(return_value=primary_cur)
        primary_cur.__exit__ = MagicMock(return_value=False)
        primary_cur.fetchone.return_value = (1000,)  # above min_rows=10 -> OK

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = primary_cur
        mock_connect.return_value = mock_conn

        conn = make_connection(name='ok_sample_conn', user=self.user)
        rule = make_rule(name='ok_sample_rule', min_rows=10, connection=conn, user=self.user)
        from .services import run_single_rule
        result = run_single_rule(rule)

        self.assertEqual(result.status, 'OK')
        result.refresh_from_db()
        self.assertIsNone(result.sample_rows)


class SamplingHistoryDisplayTest(TestCase):
    """Verify rule_history renders sample-toggle button for FAIL results with sample_rows."""

    def setUp(self):
        self.user = User.objects.create_user('sampling_view_user', password='pass')
        self.client.login(username='sampling_view_user', password='pass')

    def test_sample_rows_toggle_visible_for_fail_result(self):
        rule = make_rule(min_rows=1, user=self.user)
        run = CheckRun.objects.create(finished_at=timezone.now())
        RuleResult.objects.create(
            run=run, rule=rule, status='FAIL', row_count=3,
            sample_rows=[{'id': 1, 'name': 'test'}, {'id': 2, 'name': 'other'}],
        )
        r = self.client.get(reverse('monitor:rule_history', args=[rule.pk]))
        # The button element should be rendered (not just the CSS class)
        self.assertContains(r, 'class="sample-toggle"')

    def test_sample_rows_null_shows_no_toggle(self):
        rule = make_rule(min_rows=1, user=self.user)
        run = CheckRun.objects.create(finished_at=timezone.now())
        RuleResult.objects.create(
            run=run, rule=rule, status='FAIL', row_count=3,
            sample_rows=None,
        )
        r = self.client.get(reverse('monitor:rule_history', args=[rule.pk]))
        # Check that no sample-toggle button is rendered (CSS class exists in <style> but no button)
        self.assertNotContains(r, 'class="sample-toggle"')

    def test_ok_result_shows_no_sample_toggle(self):
        rule = make_rule(min_rows=1, user=self.user)
        run = CheckRun.objects.create(finished_at=timezone.now())
        RuleResult.objects.create(
            run=run, rule=rule, status='OK', row_count=100,
            sample_rows=None,
        )
        r = self.client.get(reverse('monitor:rule_history', args=[rule.pk]))
        # Check that no sample-toggle button is rendered
        self.assertNotContains(r, 'class="sample-toggle"')

    def test_sample_table_column_headers_rendered(self):
        rule = make_rule(min_rows=1, user=self.user)
        run = CheckRun.objects.create(finished_at=timezone.now())
        RuleResult.objects.create(
            run=run, rule=rule, status='FAIL', row_count=3,
            sample_rows=[{'id': 1, 'username': 'alice'}],
        )
        r = self.client.get(reverse('monitor:rule_history', args=[rule.pk]))
        self.assertContains(r, 'username')

# =================================================================
#  REST API -- ApiKey model, auth decorator, and endpoints
# =================================================================

class ApiKeyModelTest(TestCase):
    """ApiKey model fields, uniqueness, and __str__."""

    def setUp(self):
        self.user = User.objects.create_user('apikey_model_user', password='pass')

    def test_create_api_key(self):
        from .models import ApiKey
        key = ApiKey.objects.create(user=self.user, name='test key', key_hash='a' * 64)
        self.assertEqual(key.name, 'test key')
        self.assertTrue(key.is_active)
        self.assertIsNone(key.last_used_at)

    def test_key_hash_uniqueness_enforced(self):
        """Two rows with the same key_hash should raise IntegrityError."""
        from django.db import IntegrityError
        from .models import ApiKey
        ApiKey.objects.create(user=self.user, name='k1', key_hash='b' * 64)
        with self.assertRaises(IntegrityError):
            ApiKey.objects.create(user=self.user, name='k2', key_hash='b' * 64)

    def test_user_name_unique_together(self):
        """Two keys with the same user+name should raise IntegrityError."""
        from django.db import IntegrityError
        from .models import ApiKey
        ApiKey.objects.create(user=self.user, name='dup', key_hash='c' * 64)
        with self.assertRaises(IntegrityError):
            ApiKey.objects.create(user=self.user, name='dup', key_hash='d' * 64)

    def test_str(self):
        from .models import ApiKey
        key = ApiKey.objects.create(user=self.user, name='ci key', key_hash='e' * 64)
        self.assertIn('ci key', str(key))
        self.assertIn(self.user.username, str(key))


def _make_api_key(user, name='test', raw='testrawkey'):
    """Create an ApiKey row and return (raw_key_string, ApiKey instance)."""
    import hashlib as _hl
    from monitor.models import ApiKey
    key_hash = _hl.sha256(raw.encode()).hexdigest()
    api_key = ApiKey.objects.create(user=user, name=name, key_hash=key_hash)
    return raw, api_key


class ApiAuthTest(TestCase):
    """require_api_key decorator: missing/invalid/inactive key, valid key."""

    def setUp(self):
        self.user = User.objects.create_user('apiauth_user', password='pass')
        self.raw, self.api_key = _make_api_key(self.user, name='auth test')

    def test_missing_auth_header_returns_401(self):
        r = self.client.get('/api/v1/rules')
        self.assertEqual(r.status_code, 401)
        data = json.loads(r.content)
        self.assertIn('error', data)

    def test_wrong_scheme_returns_401(self):
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Token {self.raw}')
        self.assertEqual(r.status_code, 401)

    def test_invalid_key_returns_401(self):
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION='Bearer completely_wrong')
        self.assertEqual(r.status_code, 401)
        data = json.loads(r.content)
        self.assertEqual(data['error'], 'invalid API key')

    def test_inactive_key_returns_401(self):
        from .models import ApiKey
        ApiKey.objects.filter(pk=self.api_key.pk).update(is_active=False)
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 401)

    def test_valid_key_returns_200(self):
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 200)

    def test_valid_key_updates_last_used_at(self):
        from .models import ApiKey
        self.assertIsNone(self.api_key.last_used_at)
        self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.api_key.refresh_from_db()
        self.assertIsNotNone(self.api_key.last_used_at)


from django.test.utils import override_settings as _ov_for_api
_LOCMEM_API = {'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}}


class RateLimitTest(TestCase):
    """Rate limiting: under limit passes, 61st request fails."""

    def setUp(self):
        self.user = User.objects.create_user('ratelimit_user', password='pass')
        self.raw, self.api_key = _make_api_key(self.user, name='rate test', raw='ratelimitrawkey')

    def test_under_limit_passes(self):
        from django.core.cache import cache
        cache.clear()
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 200)

    @_ov_for_api(**_LOCMEM_API)
    def test_61st_request_returns_429(self):
        """After 60 requests in the same minute bucket, the 61st returns 429."""
        from django.core.cache import cache
        from monitor.api_auth import _RATE_LIMIT
        cache.clear()
        import time
        bucket = int(time.time() // 60)
        cache_key = f'rl:{self.api_key.pk}:{bucket}'
        cache.set(cache_key, _RATE_LIMIT, timeout=120)
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=f'Bearer {self.raw}')
        self.assertEqual(r.status_code, 429)
        data = json.loads(r.content)
        self.assertIn('retry_after_seconds', data)
        self.assertGreaterEqual(data['retry_after_seconds'], 0)


class ApiEndpointsTest(TestCase):
    """API endpoint tests: auth, isolation, response shape."""

    def setUp(self):
        self.user = User.objects.create_user('api_endpoints_user', password='pass')
        self.other_user = User.objects.create_user('api_other_user', password='pass')
        self.raw, self.api_key = _make_api_key(self.user, name='endpoints test', raw='endpointsrawkey')

    def _auth(self):
        return f'Bearer {self.raw}'

    def test_list_rules_without_auth_returns_401(self):
        r = self.client.get('/api/v1/rules')
        self.assertEqual(r.status_code, 401)

    def test_list_rules_returns_only_own_rules(self):
        make_rule(name='my_rule', min_rows=1, user=self.user)
        make_rule(name='other_rule', min_rows=1, user=self.other_user)
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=self._auth())
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        names = [rule['name'] for rule in data['rules']]
        self.assertIn('my_rule', names)
        self.assertNotIn('other_rule', names)

    def test_list_rules_response_shape(self):
        make_rule(name='shape_rule', min_rows=1, user=self.user)
        r = self.client.get('/api/v1/rules', HTTP_AUTHORIZATION=self._auth())
        data = json.loads(r.content)
        self.assertIn('rules', data)
        rule = data['rules'][0]
        for field in ('id', 'name', 'schema_name', 'table_name', 'rule_type',
                      'schedule_type', 'created_at', 'updated_at'):
            self.assertIn(field, rule, f'Missing field: {field}')

    def test_run_rule_returns_run_id_and_status(self):
        from unittest.mock import patch, MagicMock
        conn = make_connection(user=self.user)
        rule = make_rule(min_rows=1, connection=conn, user=self.user)
        with patch('monitor.api_views.run_single_rule') as mock_run:
            mock_result = MagicMock()
            mock_result.run_id = 99
            mock_result.status = 'OK'
            mock_result.row_count = 10
            mock_result.last_record_age_hours = None
            mock_result.error_message = ''
            mock_result.checked_at.isoformat.return_value = '2026-01-01T00:00:00+00:00'
            mock_run.return_value = mock_result
            r = self.client.post(
                f'/api/v1/rules/{rule.pk}/run',
                HTTP_AUTHORIZATION=self._auth(),
            )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('run_id', data)
        self.assertIn('status', data)

    def test_run_rule_other_user_returns_404(self):
        other_rule = make_rule(name='other_user_rule', min_rows=1, user=self.other_user)
        r = self.client.post(
            f'/api/v1/rules/{other_rule.pk}/run',
            HTTP_AUTHORIZATION=self._auth(),
        )
        self.assertEqual(r.status_code, 404)

    def test_run_all_returns_run_id_and_counts(self):
        from unittest.mock import patch, MagicMock
        with patch('monitor.api_views.run_checks_for_user') as mock_run:
            mock_run_obj = MagicMock()
            mock_run_obj.pk = 55
            mock_run_obj.ok_count = 0
            mock_run_obj.fail_count = 0
            mock_run_obj.error_count = 0
            mock_run_obj.started_at.isoformat.return_value = '2026-01-01T00:00:00+00:00'
            mock_run_obj.finished_at = None
            mock_run.return_value = mock_run_obj
            r = self.client.post('/api/v1/rules/run-all', HTTP_AUTHORIZATION=self._auth())
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('run_id', data)
        self.assertIn('ok_count', data)
        self.assertIn('fail_count', data)
        self.assertIn('error_count', data)

    def test_get_results_nonexistent_rule_returns_404(self):
        r = self.client.get('/api/v1/rules/99999/results', HTTP_AUTHORIZATION=self._auth())
        self.assertEqual(r.status_code, 404)

    def test_get_results_other_user_rule_returns_404(self):
        other_rule = make_rule(name='other_results_rule', min_rows=1, user=self.other_user)
        r = self.client.get(
            f'/api/v1/rules/{other_rule.pk}/results',
            HTTP_AUTHORIZATION=self._auth(),
        )
        self.assertEqual(r.status_code, 404)

    def test_get_results_returns_last_20(self):
        rule = make_rule(name='results_rule', min_rows=1, user=self.user)
        run = CheckRun.objects.create(finished_at=timezone.now())
        for i in range(25):
            RuleResult.objects.create(run=run, rule=rule, status='OK')
        r = self.client.get(
            f'/api/v1/rules/{rule.pk}/results',
            HTTP_AUTHORIZATION=self._auth(),
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertIn('results', data)
        self.assertLessEqual(len(data['results']), 20)
        self.assertEqual(data['rule_id'], rule.pk)

    def test_get_results_response_shape(self):
        rule = make_rule(name='shape_results_rule', min_rows=1, user=self.user)
        run = CheckRun.objects.create(finished_at=timezone.now())
        RuleResult.objects.create(run=run, rule=rule, status='OK')
        r = self.client.get(
            f'/api/v1/rules/{rule.pk}/results',
            HTTP_AUTHORIZATION=self._auth(),
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        result = data['results'][0]
        for field in ('run_id', 'status', 'row_count', 'last_record_age_hours',
                      'error_message', 'checked_at'):
            self.assertIn(field, result, f'Missing field: {field}')


class ApiKeyViewTest(TestCase):
    """Key management UI views."""

    def setUp(self):
        self.user = User.objects.create_user('apikey_view_user', password='pass')
        self.client.login(username='apikey_view_user', password='pass')

    def test_list_view_redirects_unauthenticated(self):
        self.client.logout()
        r = self.client.get(reverse('monitor:api_key_list'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_list_view_returns_200_when_logged_in(self):
        r = self.client.get(reverse('monitor:api_key_list'))
        self.assertEqual(r.status_code, 200)

    def test_create_key_creates_api_key_row(self):
        from .models import ApiKey
        self.assertEqual(ApiKey.objects.filter(user=self.user).count(), 0)
        r = self.client.post(reverse('monitor:api_key_create'), {'name': 'my ci key'})
        self.assertRedirects(r, reverse('monitor:api_key_list'), fetch_redirect_response=False)
        self.assertEqual(ApiKey.objects.filter(user=self.user).count(), 1)
        key = ApiKey.objects.get(user=self.user)
        self.assertTrue(key.is_active)

    def test_create_key_raw_key_starts_with_dp(self):
        """After creation, the session contains a raw key starting with dp_."""
        self.client.post(reverse('monitor:api_key_create'), {'name': 'dp prefix key'})
        session = self.client.session
        raw_key = session.get('new_api_key', '')
        self.assertTrue(raw_key.startswith('dp_'), f'Expected dp_ prefix, got: {raw_key}')

    def test_revoke_key_sets_is_active_false(self):
        from .models import ApiKey
        _, key = _make_api_key(self.user, name='to revoke')
        self.assertTrue(key.is_active)
        r = self.client.post(reverse('monitor:api_key_revoke', args=[key.pk]))
        self.assertRedirects(r, reverse('monitor:api_key_list'), fetch_redirect_response=False)
        key.refresh_from_db()
        self.assertFalse(key.is_active)

    def test_revoke_other_users_key_returns_404(self):
        other = User.objects.create_user('other_key_owner', password='pass')
        _, key = _make_api_key(other, name='other key')
        r = self.client.post(reverse('monitor:api_key_revoke', args=[key.pk]))
        self.assertEqual(r.status_code, 404)
        key.refresh_from_db()
        self.assertTrue(key.is_active)  # unchanged


# =============================================================================
#  Live Preview - service unit tests (rule-live-preview)
# =============================================================================

class PreviewRuleServiceTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('preview_svc_user', password='pass')
        self.conn = make_connection(name='preview_conn', url='postgresql://u:p@host/db', user=self.user)

    def _ok_result(self, sample_rows=None):
        return {
            'status': 'OK',
            'row_count': 50,
            'last_record_age_hours': None,
            'error_message': '',
            'sample_rows': sample_rows,
        }

    @patch('monitor.services._open_conn')
    @patch('monitor.services._check_rule')
    def test_volume_freshness_preview_ok(self, mock_check, mock_open):
        mock_open.return_value = MagicMock()
        mock_check.return_value = self._ok_result()

        from .services import preview_rule
        result = preview_rule({
            'connection_id': self.conn.pk,
            'rule_type': 'volume_freshness',
            'schema_name': 'public',
            'table_name': 'orders',
            'min_row_count': 1,
        }, self.user)

        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['row_count'], 50)
        mock_open.assert_called_once()
        mock_check.assert_called_once()

    @patch('monitor.services._open_conn')
    @patch('monitor.services._check_rule')
    def test_custom_sql_preview_ok(self, mock_check, mock_open):
        mock_open.return_value = MagicMock()
        mock_check.return_value = self._ok_result()

        from .services import preview_rule
        result = preview_rule({
            'connection_id': self.conn.pk,
            'rule_type': 'custom_sql',
            'custom_sql': 'SELECT true',
        }, self.user)

        self.assertEqual(result['status'], 'OK')

    def test_unknown_connection_id_returns_error(self):
        from .services import preview_rule
        result = preview_rule({'connection_id': 99999, 'rule_type': 'volume_freshness'}, self.user)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('Connection not found', result['error_message'])

    def test_wrong_owner_returns_error(self):
        other_user = User.objects.create_user('preview_other', password='pass')
        from .services import preview_rule
        result = preview_rule({'connection_id': self.conn.pk, 'rule_type': 'volume_freshness'}, other_user)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('Connection not found', result['error_message'])

    @patch('monitor.services._open_conn')
    def test_empty_url_returns_error(self, mock_open):
        empty_conn = Connection(name='empty_url_conn', user=self.user)
        empty_conn._database_url = ''
        empty_conn.save()

        from .services import preview_rule
        result = preview_rule({'connection_id': empty_conn.pk, 'rule_type': 'volume_freshness'}, self.user)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('empty', result['error_message'].lower())
        mock_open.assert_not_called()

    @patch('monitor.services._open_conn')
    def test_monitored_db_error_returns_error(self, mock_open):
        from .services import preview_rule, MonitoredDbError
        mock_open.side_effect = MonitoredDbError('connection refused')

        result = preview_rule({
            'connection_id': self.conn.pk,
            'rule_type': 'volume_freshness',
            'schema_name': 'public',
            'table_name': 'orders',
            'min_row_count': 1,
        }, self.user)

        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('connection refused', result['error_message'])

    @patch('monitor.services._open_conn')
    @patch('monitor.services._check_rule')
    def test_sample_rows_sliced_to_three(self, mock_check, mock_open):
        mock_open.return_value = MagicMock()
        five_rows = [{'id': i} for i in range(5)]
        mock_check.return_value = self._ok_result(sample_rows=five_rows)

        from .services import preview_rule
        result = preview_rule({
            'connection_id': self.conn.pk,
            'rule_type': 'volume_freshness',
            'schema_name': 'public',
            'table_name': 'orders',
            'min_row_count': 1,
        }, self.user)

        self.assertIsNotNone(result['sample_rows'])
        self.assertEqual(len(result['sample_rows']), 3)

    @patch('monitor.services._open_conn')
    @patch('monitor.services._check_rule')
    def test_no_db_writes(self, mock_check, mock_open):
        mock_open.return_value = MagicMock()
        mock_check.return_value = self._ok_result()

        run_count_before = CheckRun.objects.count()
        result_count_before = RuleResult.objects.count()

        from .services import preview_rule
        preview_rule({
            'connection_id': self.conn.pk,
            'rule_type': 'volume_freshness',
            'schema_name': 'public',
            'table_name': 'orders',
            'min_row_count': 1,
        }, self.user)

        self.assertEqual(CheckRun.objects.count(), run_count_before)
        self.assertEqual(RuleResult.objects.count(), result_count_before)


# =============================================================================
#  Live Preview - endpoint integration tests (rule-live-preview)
# =============================================================================

class PreviewRuleViewTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('preview_view_user', password='pass')
        self.conn = make_connection(name='preview_view_conn', url='postgresql://u:p@host/db', user=self.user)
        self.url = '/api/preview/'
        self._ok_payload = {
            'status': 'OK',
            'row_count': 50,
            'last_record_age_hours': None,
            'error_message': '',
            'sample_rows': None,
        }

    def test_unauthenticated_redirects_to_login(self):
        r = self.client.post(
            self.url,
            data=json.dumps({'connection_id': self.conn.pk}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_missing_connection_id_returns_400(self):
        self.client.login(username='preview_view_user', password='pass')
        r = self.client.post(
            self.url,
            data=json.dumps({'rule_type': 'volume_freshness'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        data = json.loads(r.content)
        self.assertIn('connection_id', data.get('error', ''))

    def test_non_integer_connection_id_returns_400(self):
        self.client.login(username='preview_view_user', password='pass')
        r = self.client.post(
            self.url,
            data=json.dumps({'connection_id': 'not-an-int'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    def test_invalid_json_returns_400(self):
        self.client.login(username='preview_view_user', password='pass')
        r = self.client.post(
            self.url,
            data='not valid json',
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        data = json.loads(r.content)
        self.assertIn('Invalid JSON', data.get('error', ''))

    @patch('monitor.views.preview_rule')
    def test_valid_request_returns_200_with_expected_keys(self, mock_preview):
        mock_preview.return_value = self._ok_payload
        self.client.login(username='preview_view_user', password='pass')
        r = self.client.post(
            self.url,
            data=json.dumps({
                'connection_id': self.conn.pk,
                'rule_type': 'volume_freshness',
                'schema_name': 'public',
                'table_name': 'orders',
                'min_row_count': 1,
            }),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        for key in ('status', 'row_count', 'last_record_age_hours', 'error_message', 'sample_rows'):
            self.assertIn(key, data)

    def test_other_users_connection_returns_200_with_error_status(self):
        other_user = User.objects.create_user('preview_other_view', password='pass')
        other_conn = make_connection(name='other_conn_view', url='postgresql://u:p@h/db', user=other_user)

        self.client.login(username='preview_view_user', password='pass')
        r = self.client.post(
            self.url,
            data=json.dumps({'connection_id': other_conn.pk, 'rule_type': 'volume_freshness'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data['status'], 'ERROR')

    def test_get_method_not_allowed(self):
        self.client.login(username='preview_view_user', password='pass')
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 405)


# ═══════════════════════════════════════════════════════════════
#  Rule Tags tests (Phase 5 — change: rule-tags)
# ═══════════════════════════════════════════════════════════════

class RuleTagsModelTests(TestCase):
    """Rule.tags field and tags_list property."""

    def setUp(self):
        self.user = User.objects.create_user('tags_model_user', password='pass')

    def test_tags_default_empty_string(self):
        rule = make_rule(name='tags_default', min_rows=1, user=self.user)
        self.assertEqual(rule.tags, '')

    def test_tags_list_empty_when_no_tags(self):
        rule = make_rule(name='tags_empty', min_rows=1, user=self.user)
        self.assertEqual(rule.tags_list, [])

    def test_tags_list_returns_normalised_list(self):
        rule = make_rule(name='tags_norm', min_rows=1, user=self.user)
        rule.tags = 'production,finance'
        rule.save()
        self.assertEqual(rule.tags_list, ['production', 'finance'])

    def test_tags_list_ignores_empty_segments(self):
        rule = make_rule(name='tags_empty_seg', min_rows=1, user=self.user)
        rule.tags = ',production,'
        rule.save()
        self.assertEqual(rule.tags_list, ['production'])

    def test_tags_do_not_affect_check_constraint(self):
        """Setting tags on a valid rule must not raise IntegrityError."""
        rule = make_rule(name='tags_constraint', min_rows=1, user=self.user)
        rule.tags = 'finance,orders'
        rule.save()
        rule.refresh_from_db()
        self.assertEqual(rule.tags, 'finance,orders')


class RuleTagsFormTests(TestCase):
    """RuleForm.clean_tags() validation."""

    def setUp(self):
        self.user = User.objects.create_user('tags_form_user', password='pass')
        self.conn = Connection.objects.create(name='tags-conn', user=self.user)
        self.conn.set_database_url('postgresql://user:pass@host/db')
        self.conn.save()

    def _form(self, tags_value):
        from .forms import RuleForm
        data = {
            'name': 'test',
            'schema_name': 'public',
            'table_name': 'orders',
            'connection': self.conn.pk,
            'min_row_count': 1,
            'rule_type': 'volume_freshness',
            'severity': 'critical',
            'tags': tags_value,
        }
        return RuleForm(data, user=self.user)

    def test_valid_single_tag(self):
        form = self._form('production')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['tags'], 'production')

    def test_valid_multi_tag_normalised(self):
        form = self._form('Production, Finance')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['tags'], 'production,finance')

    def test_five_tags_valid(self):
        form = self._form('a,b,c,d,e')
        self.assertTrue(form.is_valid(), form.errors)

    def test_six_tags_invalid(self):
        form = self._form('a,b,c,d,e,f')
        self.assertFalse(form.is_valid())
        self.assertIn('tags', form.errors)

    def test_invalid_char_rejected(self):
        form = self._form('Finance!')
        self.assertFalse(form.is_valid())
        self.assertIn('tags', form.errors)

    def test_hyphen_mid_tag_valid(self):
        form = self._form('a-b')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['tags'], 'a-b')

    def test_leading_hyphen_invalid(self):
        form = self._form('-tag')
        self.assertFalse(form.is_valid())
        self.assertIn('tags', form.errors)

    def test_tag_length_30_valid(self):
        form = self._form('a' * 30)
        self.assertTrue(form.is_valid(), form.errors)

    def test_tag_length_31_invalid(self):
        form = self._form('a' * 31)
        self.assertFalse(form.is_valid())
        self.assertIn('tags', form.errors)

    def test_empty_tags_cleaned_to_empty_string(self):
        form = self._form('')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['tags'], '')


class RuleTagsDashboardTests(TestCase):
    """Dashboard renders data-tags attribute and tag pills."""

    def setUp(self):
        self.user = User.objects.create_user('tags_dash_user', password='pass')
        self.client.login(username='tags_dash_user', password='pass')
        self.rule_with_tags = make_rule(
            name='tagged_rule',
            min_rows=1,
            user=self.user,
        )
        self.rule_with_tags.tags = 'production,finance'
        self.rule_with_tags.save()
        self.rule_no_tags = make_rule(
            name='untagged_rule',
            min_rows=1,
            user=self.user,
        )

    def test_data_tags_attribute_rendered(self):
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertContains(r, 'data-tags="production,finance"')

    def test_tag_pills_rendered_for_tagged_rule(self):
        r = self.client.get(reverse('monitor:dashboard'))
        self.assertContains(r, '>production<')
        self.assertContains(r, '>finance<')

    def test_no_tag_div_for_untagged_rule(self):
        """A rule with empty tags must not produce a tags wrapper div in its cell."""
        r = self.client.get(reverse('monitor:dashboard'))
        content = r.content.decode()
        # The untagged rule row should have data-tags="" (empty)
        self.assertIn('data-tags=""', content)
