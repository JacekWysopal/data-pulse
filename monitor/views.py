from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ConnectionForm, RuleForm
from .models import CheckRun, Connection, Rule, RuleResult
from .services import run_all_checks, run_single_rule


# ── Dashboard ────────────────────────────────────────────────

@login_required
def dashboard(request):
    rules = Rule.objects.select_related('connection').prefetch_related('results').all()
    last_run = CheckRun.objects.first()

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
        run_all_checks()
    return redirect('monitor:dashboard')


# ── Rules ─────────────────────────────────────────────────────

@login_required
def run_single(request, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id)
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
    rule = get_object_or_404(Rule, pk=rule_id)
    results = rule.results.select_related('run').order_by('-checked_at')[:20]
    return render(request, 'monitor/rule_history.html', {'rule': rule, 'results': results})


@login_required
def rule_create(request):
    if request.method == 'POST':
        form = RuleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Rule added.')
            return redirect('monitor:dashboard')
    else:
        form = RuleForm()
    return render(request, 'monitor/rule_form.html', {'form': form, 'action': 'Add rule'})


@login_required
def rule_edit(request, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id)
    if request.method == 'POST':
        form = RuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            messages.success(request, 'Rule updated.')
            return redirect('monitor:dashboard')
    else:
        form = RuleForm(instance=rule)
    return render(request, 'monitor/rule_form.html', {'form': form, 'action': 'Edit rule', 'rule': rule})


@login_required
def rule_delete(request, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id)
    if request.method == 'POST':
        name = str(rule)
        rule.delete()
        messages.success(request, f'Rule "{name}" deleted.')
        return redirect('monitor:dashboard')
    return render(request, 'monitor/rule_confirm_delete.html', {'rule': rule})


# ── Connections ───────────────────────────────────────────────

@login_required
def connection_list(request):
    connections = Connection.objects.prefetch_related('rules').all()
    return render(request, 'monitor/connection_list.html', {'connections': connections})


@login_required
def connection_create(request):
    if request.method == 'POST':
        form = ConnectionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Connection added.')
            return redirect('monitor:connection_list')
    else:
        form = ConnectionForm()
    return render(request, 'monitor/connection_form.html', {'form': form, 'action': 'Add connection'})


@login_required
def connection_edit(request, conn_id):
    conn = get_object_or_404(Connection, pk=conn_id)
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
    conn = get_object_or_404(Connection, pk=conn_id)
    if request.method == 'POST':
        name = conn.name
        conn.delete()
        messages.success(request, f'Connection "{name}" deleted.')
        return redirect('monitor:connection_list')
    return render(request, 'monitor/connection_confirm_delete.html', {'conn': conn})
