# monitor/api_urls.py
"""URL patterns for the DataPulse REST API v1, mounted at /api/v1/ in data_pulse/urls.py."""
from django.urls import path

from . import api_views

# NOTE: 'rules/run-all' must come before 'rules/<int:rule_id>/run' so Django
# doesn't try to parse "run-all" as an integer for rule_id.
urlpatterns = [
    path('rules/run-all', api_views.api_run_all, name='api_run_all'),
    path('rules/<int:rule_id>/run', api_views.api_run_rule, name='api_run_rule'),
    path('rules', api_views.api_list_rules, name='api_list_rules'),
    path('rules/<int:rule_id>/results', api_views.api_get_results, name='api_get_results'),
]
