# monitor/api_views.py
"""
REST API endpoint views for the DataPulse public API (v1).

All views are protected by @require_api_key, which validates the
Authorization: Bearer <token> header and enforces 60 req/min rate limiting.
All views return JsonResponse; no HTML or session auth involved.
"""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .api_auth import require_api_key
from .models import Rule, RuleResult
from .services import run_checks_for_user, run_single_rule


@csrf_exempt
@require_api_key
@require_POST
def api_run_rule(request, rule_id):
    """POST /api/v1/rules/{id}/run — run a single rule owned by the authenticated user."""
    rule = get_object_or_404(Rule, pk=rule_id, user=request.api_user)
    result = run_single_rule(rule)
    return JsonResponse({
        'run_id': result.run_id,
        'rule_id': rule_id,
        'status': result.status,
        'row_count': result.row_count,
        'last_record_age_hours': result.last_record_age_hours,
        'error_message': result.error_message,
        'checked_at': result.checked_at.isoformat(),
    })


@csrf_exempt
@require_api_key
@require_POST
def api_run_all(request):
    """POST /api/v1/rules/run-all — run all rules owned by the authenticated user."""
    run = run_checks_for_user(request.api_user)
    return JsonResponse({
        'run_id': run.pk,
        'started_at': run.started_at.isoformat(),
        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
        'ok_count': run.ok_count,
        'fail_count': run.fail_count,
        'error_count': run.error_count,
    })


@csrf_exempt
@require_api_key
@require_GET
def api_list_rules(request):
    """GET /api/v1/rules — list all rules owned by the authenticated user."""
    rules = Rule.objects.filter(user=request.api_user).values(
        'id', 'name', 'schema_name', 'table_name',
        'rule_type', 'schedule_type', 'created_at', 'updated_at',
    )
    rules_list = []
    for r in rules:
        rules_list.append({
            'id': r['id'],
            'name': r['name'],
            'schema_name': r['schema_name'],
            'table_name': r['table_name'],
            'rule_type': r['rule_type'],
            'schedule_type': r['schedule_type'],
            'created_at': r['created_at'].isoformat(),
            'updated_at': r['updated_at'].isoformat(),
        })
    return JsonResponse({'rules': rules_list})


@csrf_exempt
@require_api_key
@require_GET
def api_get_results(request, rule_id):
    """GET /api/v1/rules/{id}/results — return last 20 results for a rule.

    Ownership is enforced by scoping the Rule lookup to user=request.api_user.
    RuleResult.rule always FK-points to the owning Rule, so no secondary
    ownership check on results is needed.
    """
    rule = get_object_or_404(Rule, pk=rule_id, user=request.api_user)
    results = (
        RuleResult.objects
        .filter(rule=rule)
        .order_by('-checked_at')[:20]
    )
    results_list = [
        {
            'run_id': r.run_id,
            'status': r.status,
            'row_count': r.row_count,
            'last_record_age_hours': r.last_record_age_hours,
            'error_message': r.error_message,
            'checked_at': r.checked_at.isoformat(),
        }
        for r in results
    ]
    return JsonResponse({
        'rule_id': rule_id,
        'rule_name': rule.name,
        'results': results_list,
    })
