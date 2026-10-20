from django.urls import path

from . import views

app_name = 'monitor'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('run/', views.run_checks, name='run_checks'),
    path('rules/new/', views.rule_create, name='rule_create'),
    path('rules/<int:rule_id>/', views.rule_history, name='rule_history'),
    path('rules/<int:rule_id>/edit/', views.rule_edit, name='rule_edit'),
    path('rules/<int:rule_id>/delete/', views.rule_delete, name='rule_delete'),
]
