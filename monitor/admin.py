from django.contrib import admin

from .models import CheckRun, Rule, RuleResult


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'schema_name', 'table_name', 'min_row_count', 'max_age_hours', 'timestamp_column']
    search_fields = ['name', 'schema_name', 'table_name']


@admin.register(CheckRun)
class CheckRunAdmin(admin.ModelAdmin):
    list_display = ['started_at', 'finished_at']
    readonly_fields = ['started_at', 'finished_at']


@admin.register(RuleResult)
class RuleResultAdmin(admin.ModelAdmin):
    list_display = ['rule', 'run', 'status', 'row_count', 'last_record_age_hours', 'checked_at']
    list_filter = ['status']
    readonly_fields = ['checked_at']
