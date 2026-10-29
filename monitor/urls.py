from django.urls import path
from . import views

app_name = 'monitor'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('run/', views.run_checks, name='run_checks'),

    # Rules
    path('rules/new/', views.rule_create, name='rule_create'),
    path('rules/<int:rule_id>/', views.rule_history, name='rule_history'),
    path('rules/<int:rule_id>/run/', views.run_single, name='run_single'),
    path('rules/<int:rule_id>/edit/', views.rule_edit, name='rule_edit'),
    path('rules/<int:rule_id>/delete/', views.rule_delete, name='rule_delete'),
    path('rules/<int:rule_id>/clone/', views.rule_clone, name='rule_clone'),

    # Schema introspection (S-04)
    path('api/schema/<int:conn_id>/tables/', views.api_schema_tables, name='api_schema_tables'),
    path('api/schema/<int:conn_id>/columns/<str:schema>/<str:table>/', views.api_schema_columns, name='api_schema_columns'),

    # Live preview (rule-live-preview)
    path('api/preview/', views.preview_rule_view, name='api_preview_rule'),

    # Template catalog (check-templates)
    path('api/templates/', views.api_templates, name='api_templates'),

    # dbt webhook
    path('api/v1/webhooks/dbt/', views.dbt_webhook, name='dbt_webhook'),

    # Connections
    path('connections/', views.connection_list, name='connection_list'),
    path('connections/new/', views.connection_create, name='connection_create'),
    path('connections/<int:conn_id>/edit/', views.connection_edit, name='connection_edit'),
    path('connections/<int:conn_id>/delete/', views.connection_delete, name='connection_delete'),

    # Schedule
    path('schedule/', views.schedule_dashboard, name='schedule_dashboard'),
    path('schedule/<int:rule_id>/toggle/', views.toggle_schedule, name='toggle_schedule'),

    # dbt Integrations UI
    path('integrations/dbt/', views.dbt_integration_list, name='dbt_integration_list'),
    path('integrations/dbt/new/', views.dbt_integration_create, name='dbt_integration_create'),
    path('integrations/dbt/<int:pk>/edit/', views.dbt_integration_edit, name='dbt_integration_edit'),
    path('integrations/dbt/<int:pk>/delete/', views.dbt_integration_delete, name='dbt_integration_delete'),

    # Slack Webhooks
    path('slack-webhooks/', views.slack_webhook_list, name='slack_webhook_list'),
    path('slack-webhooks/new/', views.slack_webhook_create, name='slack_webhook_create'),
    path('slack-webhooks/<int:wh_id>/edit/', views.slack_webhook_edit, name='slack_webhook_edit'),
    path('slack-webhooks/<int:wh_id>/delete/', views.slack_webhook_delete, name='slack_webhook_delete'),

    # API key management
    path('settings/api-keys/', views.api_key_list, name='api_key_list'),
    path('settings/api-keys/new/', views.api_key_create, name='api_key_create'),
    path('settings/api-keys/<int:key_id>/revoke/', views.api_key_revoke, name='api_key_revoke'),

    # Notification settings
    path('settings/notifications/', views.notification_settings, name='settings'),
]
