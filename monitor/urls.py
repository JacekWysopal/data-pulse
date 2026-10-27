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

    # Schema introspection (S-04)
    path('api/schema/<int:conn_id>/tables/', views.api_schema_tables, name='api_schema_tables'),
    path('api/schema/<int:conn_id>/columns/<str:schema>/<str:table>/', views.api_schema_columns, name='api_schema_columns'),

    # Connections
    path('connections/', views.connection_list, name='connection_list'),
    path('connections/new/', views.connection_create, name='connection_create'),
    path('connections/<int:conn_id>/edit/', views.connection_edit, name='connection_edit'),
    path('connections/<int:conn_id>/delete/', views.connection_delete, name='connection_delete'),
]
