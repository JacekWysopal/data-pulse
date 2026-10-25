from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import RuleForm
from .models import CheckRun, Rule, RuleResult
from .services import run_all_checks


@login_required
def dashboard(request):
    """Widok główny: lista reguł ze statusem ostatniego przebiegu."""
    rules = Rule.objects.prefetch_related('results').all()
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
        rule_status.append({
            'rule': rule,
            'result': last_result,
            'status': status,
        })

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
    """Uruchamia sprawdzenie wszystkich reguł (POST)."""
    if request.method == 'POST':
        run = run_all_checks()
        fail_count = run.fail_count
        error_count = run.error_count
        ok_count = run.ok_count

        if error_count:
            messages.warning(request, f'Przebieg zakończony: {ok_count} OK, {fail_count} FAIL, {error_count} ERROR.')
        elif fail_count:
            messages.warning(request, f'Przebieg zakończony: {ok_count} OK, {fail_count} FAIL.')
        else:
            messages.success(request, f'Przebieg zakończony: {ok_count} OK — wszystkie reguły spełnione.')

    return redirect('monitor:dashboard')


@login_required
def rule_history(request, rule_id):
    """Historia wyników dla jednej reguły."""
    rule = get_object_or_404(Rule, pk=rule_id)
    results = rule.results.select_related('run').order_by('-checked_at')[:20]

    return render(request, 'monitor/rule_history.html', {
        'rule': rule,
        'results': results,
    })


@login_required
def rule_create(request):
    """Formularz tworzenia nowej reguły."""
    if request.method == 'POST':
        form = RuleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Reguła została dodana.')
            return redirect('monitor:dashboard')
    else:
        form = RuleForm()

    return render(request, 'monitor/rule_form.html', {'form': form, 'action': 'Dodaj regułę'})


@login_required
def rule_edit(request, rule_id):
    """Formularz edycji istniejącej reguły."""
    rule = get_object_or_404(Rule, pk=rule_id)
    if request.method == 'POST':
        form = RuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            messages.success(request, 'Reguła została zaktualizowana.')
            return redirect('monitor:dashboard')
    else:
        form = RuleForm(instance=rule)

    return render(request, 'monitor/rule_form.html', {'form': form, 'action': 'Edytuj regułę', 'rule': rule})


@login_required
def rule_delete(request, rule_id):
    """Usunięcie reguły (POST)."""
    rule = get_object_or_404(Rule, pk=rule_id)
    if request.method == 'POST':
        rule_name = str(rule)
        rule.delete()
        messages.success(request, f'Reguła „{rule_name}" została usunięta.')
        return redirect('monitor:dashboard')

    return render(request, 'monitor/rule_confirm_delete.html', {'rule': rule})
