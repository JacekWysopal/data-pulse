import hashlib
import hmac as _hmac
import json
import secrets
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from .forms import ConnectionForm, DbtIntegrationForm, RuleForm, SignupForm, SlackWebhookForm
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .check_templates import TEMPLATES as CHECK_TEMPLATES
from .models import ApiKey, CheckRun, Connection, DbtIntegration, Rule, RuleResult, SlackWebhook, UserProfile
from .schedule_utils import get_next_run
from .services import get_schema_columns, get_schema_tables, run_all_checks, run_checks_for_user, run_single_rule


# ── Authentication ──────────────────────────────────────────

def signup(request):
    """Public signup view — no @login_required."""
    if request.user.is_authenticated:
        return redirect('monitor:dashboard')
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = SignupForm()
    return render(request, 'signup.html', {'form': form})


# ── Dashboard ────────────────────────────────────────────────

@login_required
def dashboard(request):
    rules = Rule.objects.select_related('connection').prefetch_related('results').filter(user=request.user)
    last_run = CheckRun.objects.filter(results__rule__user=request.user).distinct().order_by('-started_at').first()

    ok_count = fail_count = error_count = never_count = 0
    rule_status = []
    for rule in rules:
        last_result = rule.results.order_by('-checked_at').first()
        status = last_result.status if last_result else 'NEVER_RUN'
        if status == 'OK':
            ok_count += 1
        elif status == 'FAIL':
            fail_count += 1
        elif status == 'ERROR':
            error_count += 1
        else:
            never_count += 1
        rule_status.append({'rule': rule, 'result': last_result, 'status': status})

    return render(request, 'monitor/dashboard.html', {
        'rule_status': rule_status,
        'last_run': last_run,
        'ok_count': ok_count,
        'fail_count': fail_count,
        'error_count': error_count,
        'never_count': never_count,
        'total_count': len(rule_status),
    })


@login_required
def run_checks(request):
    if request.method == 'POST':
        run_checks_for_user(request.user)
    return redirect('monitor:dashboard')


# ── Rules ─────────────────────────────────────────────────────

@login_required
def run_single(request, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id, user=request.user)
    if request.method == 'POST':
        result = run_single_rule(rule)
        if result.status == 'OK':
            messages.success(request, f'✓ {rule.name}: OK')
        elif result.status == 'FAIL':
            messages.warning(request, f'✗ {rule.name}: FAIL')
        else:
            messages.warning(request, f'⚠ {rule.name}: ERROR — {result.error_message[:80]}')
    return redirect('monitor:dashboard')


@login_required
def rule_history(request, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id, user=request.user)
    results = rule.results.select_related('run').order_by('-checked_at')[:20]
    return render(request, 'monitor/rule_history.html', {'rule': rule, 'results': results})


@login_required
def rule_create(request):
    if request.method == 'POST':
        form = RuleForm(request.POST, user=request.user)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.user = request.user
            rule.save()
            messages.success(request, 'Rule added.')
            return redirect('monitor:dashboard')
    else:
        form = RuleForm(user=request.user)
    return render(request, 'monitor/rule_form.html', {'form': form, 'action': 'Add rule'})


@login_required
def rule_edit(request, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id, user=request.user)
    if request.method == 'POST':
        form = RuleForm(request.POST, instance=rule, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Rule updated.')
            return redirect('monitor:dashboard')
    else:
        form = RuleForm(instance=rule, user=request.user)
    return render(request, 'monitor/rule_form.html', {'form': form, 'action': 'Edit rule', 'rule': rule})


@login_required
def rule_delete(request, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id, user=request.user)
    if request.method == 'POST':
        name = str(rule)
        rule.delete()
        messages.success(request, f'Rule "{name}" deleted.')
        return redirect('monitor:dashboard')
    return render(request, 'monitor/rule_confirm_delete.html', {'rule': rule})


# ── Schema introspection (S-04) ─────────────────────────────

CACHE_KEY_TABLES  = 'dp_schema_tables_{}'
CACHE_KEY_COLUMNS = 'dp_schema_cols_{}_{}_{}'  # conn_id, schema, table


@login_required
@require_GET
def api_schema_tables(request, conn_id):
    """AJAX: list tables for a connection. Session-cached 5 min."""
    # Verify ownership before accessing the connection
    get_object_or_404(Connection, pk=conn_id, user=request.user)
    cache_key = CACHE_KEY_TABLES.format(conn_id)
    cached = request.session.get(cache_key)
    if cached:
        return JsonResponse(cached)
    result = get_schema_tables(conn_id)
    if not result['error']:
        request.session[cache_key] = result
    return JsonResponse(result)


@login_required
@require_GET
def api_schema_columns(request, conn_id, schema, table):
    """AJAX: list columns for schema.table. Session-cached 5 min."""
    # Verify ownership before accessing the connection
    get_object_or_404(Connection, pk=conn_id, user=request.user)
    cache_key = CACHE_KEY_COLUMNS.format(conn_id, schema, table)
    cached = request.session.get(cache_key)
    if cached:
        return JsonResponse(cached)
    result = get_schema_columns(conn_id, schema, table)
    if not result['error']:
        request.session[cache_key] = result
    return JsonResponse(result)




@login_required
@require_GET
def api_templates(request):
    """AJAX: return the built-in check template catalog as JSON.

    GET /api/templates/
    Returns: {"templates": [...]}
    Each entry has: id, label, description, params, sql (dict keyed by provider).
    Requires authentication; unauthenticated requests get 302 redirect to login.
    """
    return JsonResponse({'templates': CHECK_TEMPLATES})


# ── Schedule ─────────────────────────────────────────────────

@login_required
def schedule_dashboard(request):
    """Show all scheduled rules with next-run time, last result, and toggle."""
    from django.utils import timezone
    now = timezone.now()
    rules = (
        Rule.objects
        .select_related('connection')
        .prefetch_related('results')
        .filter(user=request.user)
        .exclude(schedule_type='disabled')
    )
    rule_rows = []
    for rule in rules:
        next_run = get_next_run(rule)
        rule_rows.append({
            'rule': rule,
            'next_run': next_run,
            'last_result': rule.last_result,
        })
    return render(request, 'monitor/schedule_dashboard.html', {
        'rule_rows': rule_rows,
        'now': now,
    })


@login_required
@require_POST
def toggle_schedule(request, rule_id):
    """POST-only: toggle a rule between disabled and preset_1x."""
    rule = get_object_or_404(Rule, pk=rule_id, user=request.user)
    if rule.schedule_type == 'disabled':
        rule.schedule_type = 'preset_1x'
    else:
        rule.schedule_type = 'disabled'
    rule.save(update_fields=['schedule_type'])
    return redirect('monitor:schedule_dashboard')


# ── Connections ───────────────────────────────────────────────

@login_required
def connection_list(request):
    connections = Connection.objects.prefetch_related('rules').filter(user=request.user)
    return render(request, 'monitor/connection_list.html', {'connections': connections})


@login_required
def connection_create(request):
    if request.method == 'POST':
        form = ConnectionForm(request.POST)
        if form.is_valid():
            conn = form.save(commit=False)
            conn.user = request.user
            conn.save()
            messages.success(request, 'Connection added.')
            return redirect('monitor:connection_list')
    else:
        initial = {}
        provider_param = request.GET.get('provider')
        if provider_param:
            initial['provider'] = provider_param
        form = ConnectionForm(initial=initial)
    return render(request, 'monitor/connection_form.html', {'form': form, 'action': 'Add connection'})


@login_required
def connection_edit(request, conn_id):
    conn = get_object_or_404(Connection, pk=conn_id, user=request.user)
    if request.method == 'POST':
        form = ConnectionForm(request.POST, instance=conn)
        if form.is_valid():
            form.save()
            messages.success(request, 'Connection updated.')
            return redirect('monitor:connection_list')
    else:
        form = ConnectionForm(instance=conn)
    return render(request, 'monitor/connection_form.html', {'form': form, 'action': 'Edit connection', 'conn': conn})


@login_required
def connection_delete(request, conn_id):
    conn = get_object_or_404(Connection, pk=conn_id, user=request.user)
    if request.method == 'POST':
        name = conn.name
        conn.delete()
        messages.success(request, f'Connection "{name}" deleted.')
        return redirect('monitor:connection_list')
    return render(request, 'monitor/connection_confirm_delete.html', {'conn': conn})


# ── dbt Webhook ────────────────────────────────────────────

@csrf_exempt
@require_POST
def dbt_webhook(request):
    """Public endpoint: accept dbt Cloud / dbt Core job-completion events.

    Authentication: HMAC-SHA256 via ``Authorization: sha256=<hex>`` header.
    Payload shapes:
      - dbt Cloud: ``{"data": {"jobId": "<id>", "runStatus": "Success"}}``
      - dbt Core flat: ``{"job_id": "<id>", "run_status": "Success"}``
    """
    try:
        body = request.body
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Normalise payload — dbt Cloud (nested) vs dbt Core (flat)
    data = payload.get('data')
    if isinstance(data, dict):
        job_id = str(data.get('jobId', ''))
        run_status = str(data.get('runStatus', ''))
    else:
        job_id = str(payload.get('job_id', ''))
        run_status = str(payload.get('run_status', ''))

    if not job_id:
        return JsonResponse({'error': 'Missing job_id'}, status=400)

    # HMAC-SHA256 validation — use compare_digest to prevent timing attacks
    auth_header = request.headers.get('Authorization', '')
    incoming_sig = auth_header.removeprefix('sha256=')

    integrations = DbtIntegration.objects.filter(job_id=job_id).prefetch_related('rules')
    valid_integrations = []
    for integration in integrations:
        secret = integration.get_secret_key()
        expected = _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # compare_digest is mandatory: it prevents timing-based secret enumeration
        if _hmac.compare_digest(expected, incoming_sig):
            valid_integrations.append(integration)

    if not valid_integrations:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    if run_status.lower() != 'success':
        return JsonResponse({'status': 'ignored', 'run_status': run_status}, status=200)

    # Trigger mapped rules for all matching integrations
    results = []
    for integration in valid_integrations:
        for rule in integration.rules.all():
            result = run_single_rule(rule)
            results.append({'rule': rule.name, 'status': result.status})

    return JsonResponse({'status': 'ok', 'triggered': len(results), 'results': results})


# ── dbt Integrations UI ───────────────────────────────────

@login_required
def dbt_integration_list(request):
    integrations = DbtIntegration.objects.prefetch_related('rules').filter(user=request.user)
    return render(request, 'monitor/dbt_integration_list.html', {'integrations': integrations})


@login_required
def dbt_integration_create(request):
    if request.method == 'POST':
        form = DbtIntegrationForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            raw_key = secrets.token_hex(32)
            obj.set_secret_key(raw_key)
            obj.save()
            form.save_m2m()  # save ManyToMany rules
            return render(request, 'monitor/dbt_integration_form.html', {
                'form': DbtIntegrationForm(user=request.user),
                'action': 'New integration',
                'raw_secret_key': raw_key,
                'created_name': obj.name,
            })
    else:
        form = DbtIntegrationForm(user=request.user)
    return render(request, 'monitor/dbt_integration_form.html', {'form': form, 'action': 'New integration'})


@login_required
def dbt_integration_edit(request, pk):
    integration = get_object_or_404(DbtIntegration, pk=pk, user=request.user)
    if request.method == 'POST':
        form = DbtIntegrationForm(request.POST, instance=integration, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Integration updated.')
            return redirect('monitor:dbt_integration_list')
    else:
        form = DbtIntegrationForm(instance=integration, user=request.user)
    return render(request, 'monitor/dbt_integration_form.html', {
        'form': form, 'action': 'Edit integration', 'integration': integration,
    })


@login_required
def dbt_integration_delete(request, pk):
    integration = get_object_or_404(DbtIntegration, pk=pk, user=request.user)
    if request.method == 'POST':
        name = integration.name
        integration.delete()
        messages.success(request, f'Integration "{name}" deleted.')
        return redirect('monitor:dbt_integration_list')
    return render(request, 'monitor/dbt_integration_confirm_delete.html', {'integration': integration})


# ── Slack Webhooks ────────────────────────────────────────────

@login_required
def slack_webhook_list(request):
    webhooks = request.user.slack_webhooks.all()
    return render(request, 'monitor/slack_webhook_list.html', {'webhooks': webhooks})


@login_required
def slack_webhook_create(request):
    if request.method == 'POST':
        form = SlackWebhookForm(request.POST)
        if form.is_valid():
            wh = form.save(commit=False)
            wh.user = request.user
            wh.save()
            messages.success(request, 'Slack webhook added.')
            return redirect('monitor:slack_webhook_list')
    else:
        form = SlackWebhookForm()
    return render(request, 'monitor/slack_webhook_form.html', {'form': form, 'action': 'Add Slack webhook'})


@login_required
def slack_webhook_edit(request, wh_id):
    wh = get_object_or_404(SlackWebhook, pk=wh_id, user=request.user)
    if request.method == 'POST':
        form = SlackWebhookForm(request.POST, instance=wh)
        if form.is_valid():
            form.save()
            messages.success(request, 'Slack webhook updated.')
            return redirect('monitor:slack_webhook_list')
    else:
        form = SlackWebhookForm(instance=wh)
    return render(request, 'monitor/slack_webhook_form.html', {'form': form, 'action': 'Edit Slack webhook', 'wh': wh})


@login_required
def slack_webhook_delete(request, wh_id):
    wh = get_object_or_404(SlackWebhook, pk=wh_id, user=request.user)
    if request.method == 'POST':
        name = wh.name
        wh.delete()
        messages.success(request, f'Slack webhook "{name}" deleted.')
        return redirect('monitor:slack_webhook_list')
    return render(request, 'monitor/slack_webhook_confirm_delete.html', {'wh': wh})


# ── Notification Settings ─────────────────────────────────────────

_VALID_MODES = {'immediate', 'digest'}


@login_required
def notification_settings(request):
    """GET renders current notification mode; POST saves the chosen mode."""
    from django.http import HttpResponseBadRequest
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        mode = request.POST.get('notification_mode', '')
        if mode not in _VALID_MODES:
            return HttpResponseBadRequest('Invalid notification_mode value.')
        profile.notification_mode = mode
        profile.save(update_fields=['notification_mode'])
        messages.success(request, 'Notification settings saved.')
        return redirect('monitor:settings')
    return render(request, 'monitor/settings.html', {'profile': profile})


# ── API Key Management ──────────────────────────────────────────

@login_required
def api_key_list(request):
    """List all API keys for the user; show raw key once after creation."""
    keys = ApiKey.objects.filter(user=request.user)
    new_key = request.session.pop('new_api_key', None)
    return render(request, 'monitor/api_key_list.html', {
        'keys': keys,
        'new_key': new_key,
    })


@login_required
@require_POST
def api_key_create(request):
    """Generate a new API key, store hash, show raw key once via session."""
    name = request.POST.get('name', '').strip()
    if not name:
        messages.error(request, 'Key name is required.')
        return redirect('monitor:api_key_list')
    raw = 'dp_' + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    try:
        ApiKey.objects.create(user=request.user, name=name, key_hash=key_hash)
    except Exception:
        messages.error(request, f'A key named "{name}" already exists.')
        return redirect('monitor:api_key_list')
    request.session['new_api_key'] = raw
    return redirect('monitor:api_key_list')


@login_required
@require_POST
def api_key_revoke(request, key_id):
    """Soft-revoke an API key by setting is_active=False."""
    key = get_object_or_404(ApiKey, pk=key_id, user=request.user)
    ApiKey.objects.filter(pk=key.pk).update(is_active=False)
    messages.success(request, f'Key "{key.name}" revoked.')
    return redirect('monitor:api_key_list')

