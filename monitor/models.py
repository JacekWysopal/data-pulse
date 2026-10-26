from django.db import models
from django.utils import timezone
from django.conf import settings
import base64
import os

try:
    from cryptography.fernet import Fernet
    _FERNET_AVAILABLE = True
except ImportError:
    _FERNET_AVAILABLE = False


def _get_fernet():
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
    if not key or not _FERNET_AVAILABLE:
        return None
    return Fernet(key.encode() if isinstance(key, str) else key)


class Connection(models.Model):
    """Named PostgreSQL connection managed by the user via UI."""

    name = models.CharField(max_length=200, unique=True)
    description = models.CharField(max_length=500, blank=True)
    _database_url = models.TextField(db_column='database_url')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def set_database_url(self, url):
        f = _get_fernet()
        if f:
            self._database_url = f.encrypt(url.encode()).decode()
        else:
            self._database_url = url

    def get_database_url(self):
        f = _get_fernet()
        if f:
            try:
                return f.decrypt(self._database_url.encode()).decode()
            except Exception:
                return self._database_url
        return self._database_url

    @property
    def masked_url(self):
        """Return URL with password replaced by ***."""
        url = self.get_database_url()
        if not url:
            return ''
        try:
            from urllib.parse import urlparse, urlunparse
            p = urlparse(url)
            masked = p._replace(password='***')
            return urlunparse(masked)
        except Exception:
            return '***'


class Rule(models.Model):
    """Monitoring rule for one PostgreSQL table."""

    name = models.CharField(max_length=200, verbose_name='Rule name')
    schema_name = models.CharField(max_length=100, verbose_name='Schema')
    table_name = models.CharField(max_length=100, verbose_name='Table')

    connection = models.ForeignKey(
        Connection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rules',
        verbose_name='Connection',
        help_text='Leave empty to use the default MONITORED_DATABASE_URL from environment.',
    )

    timestamp_column = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Timestamp column',
        help_text='Column name for freshness check (optional)',
    )
    max_age_hours = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Max record age (hours)',
    )

    min_row_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Min row count',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['schema_name', 'table_name', 'name']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(timestamp_column__gt='', max_age_hours__isnull=False)
                    | models.Q(min_row_count__isnull=False)
                ),
                name='rule_has_at_least_one_condition',
            )
        ]

    def __str__(self):
        return f'{self.name} ({self.schema_name}.{self.table_name})'

    @property
    def full_table_name(self):
        return f'"{self.schema_name}"."{self.table_name}"'

    @property
    def last_result(self):
        return self.results.order_by('-checked_at').first()


class CheckRun(models.Model):
    """One execution of all monitoring rules."""

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'Run {self.started_at:%Y-%m-%d %H:%M:%S}'

    @property
    def ok_count(self):
        return self.results.filter(status=RuleResult.Status.OK).count()

    @property
    def fail_count(self):
        return self.results.filter(status=RuleResult.Status.FAIL).count()

    @property
    def error_count(self):
        return self.results.filter(status=RuleResult.Status.ERROR).count()


class RuleResult(models.Model):
    """Result of checking one rule in one run."""

    class Status(models.TextChoices):
        OK = 'OK', 'OK'
        FAIL = 'FAIL', 'FAIL'
        ERROR = 'ERROR', 'Error'

    run = models.ForeignKey(CheckRun, on_delete=models.CASCADE, related_name='results')
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name='results')
    checked_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=10, choices=Status.choices)

    row_count = models.PositiveIntegerField(null=True, blank=True)
    last_record_age_hours = models.FloatField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-checked_at']

    def __str__(self):
        return f'{self.rule.name}: {self.status} @ {self.checked_at:%Y-%m-%d %H:%M}'
