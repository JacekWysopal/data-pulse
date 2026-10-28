from django.db import models
from django.utils import timezone
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
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
    """Named database connection (PostgreSQL or MySQL) managed by the user via UI."""

    class Provider(models.TextChoices):
        POSTGRESQL = 'postgresql', 'PostgreSQL'
        MYSQL      = 'mysql',      'MySQL'

    name = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True)
    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.POSTGRESQL,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='connections',
    )
    _database_url = models.TextField(db_column='database_url')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('user', 'name')]

    def __str__(self):
        return f'{self.name} ({self.get_provider_display()})'

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

    class RuleType(models.TextChoices):
        VOLUME_FRESHNESS = 'volume_freshness', 'Volume / Freshness'
        CUSTOM_SQL       = 'custom_sql',       'Custom SQL'

    name = models.CharField(max_length=200, verbose_name='Rule name')
    schema_name = models.CharField(max_length=100, blank=True, verbose_name='Schema')
    table_name  = models.CharField(max_length=100, blank=True, verbose_name='Table')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rules',
    )
    connection = models.ForeignKey(
        Connection,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rules',
        verbose_name='Connection',
        help_text='Select a connection. Rules without a connection will return ERROR.',
    )

    rule_type = models.CharField(
        max_length=30,
        choices=RuleType.choices,
        default=RuleType.VOLUME_FRESHNESS,
        verbose_name='Rule type',
    )

    # Custom SQL
    custom_sql = models.TextField(
        blank=True,
        verbose_name='Custom SQL',
        help_text=(
            'SELECT query returning a single boolean-like value. '
            'true / 1 = OK, false / 0 / NULL / empty = FAIL. '
            'Must start with SELECT.'
        ),
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

    class ScheduleType(models.TextChoices):
        DISABLED    = 'disabled',    'Disabled'
        PRESET_1X   = 'preset_1x',   'Once daily (08:00 UTC)'
        PRESET_2X   = 'preset_2x',   'Twice daily (08:00 & 20:00 UTC)'
        PRESET_3X   = 'preset_3x',   'Three times daily (06:00, 14:00, 22:00 UTC)'
        PRESET_6X   = 'preset_6x',   'Six times daily (every 4 h)'
        HOURLY      = 'hourly',      'Hourly'
        CUSTOM_CRON = 'custom_cron', 'Custom cron expression'

    schedule_type = models.CharField(
        max_length=20,
        choices=ScheduleType.choices,
        default='disabled',
        verbose_name='Schedule',
    )
    schedule_cron = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Cron expression',
        help_text='5-field UTC cron, e.g. 0 8 * * *. Only when schedule_type = custom_cron.',
    )

    notify_on_fail = models.BooleanField(
        default=False,
        verbose_name='Notify on failure',
        help_text='Send an email to the rule owner when this rule returns FAIL or ERROR.',
    )
    last_notified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Last notified at',
    )
    notify_slack = models.BooleanField(
        default=False,
        verbose_name='Notify via Slack',
        help_text='Send a Slack message to the rule owner when this rule returns FAIL or ERROR.',
    )
    last_slack_notified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Last Slack notified at',
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
                    | models.Q(rule_type='custom_sql', custom_sql__gt='')
                ),
                name='rule_has_at_least_one_condition',
            )
        ]

    def __str__(self):
        return f'{self.name} ({self.schema_name}.{self.table_name})'

    @property
    def full_table_name(self):
        if self.schema_name and self.table_name:
            return f'"{self.schema_name}"."{self.table_name}"'
        return None

    @property
    def is_custom_sql(self):
        return self.rule_type == self.RuleType.CUSTOM_SQL

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
    sample_rows = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-checked_at']

    def __str__(self):
        return f'{self.rule.name}: {self.status} @ {self.checked_at:%Y-%m-%d %H:%M}'


class SlackNotification(models.Model):
    """Stub model for Slack notification settings — webhook destination and feature flag."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='slack_notifications',
    )
    webhook_url = models.CharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'SlackNotification(user={self.user_id}, enabled={self.enabled})'


class SlackWebhook(models.Model):
    """Named Slack Incoming Webhook endpoint owned by a user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='slack_webhooks',
    )
    name = models.CharField(max_length=100)
    url = models.CharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('user', 'name')]

    def __str__(self):
        return self.name


class DbtIntegration(models.Model):
    """Maps a dbt job to a set of DataPulse rules to run after the job succeeds."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='dbt_integrations',
    )
    name = models.CharField(max_length=200)
    connection = models.ForeignKey(
        'Connection',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='dbt_integrations',
    )
    job_id = models.CharField(
        max_length=200,
        help_text='dbt Cloud job ID or any string identifier for dbt Core.',
    )
    # Fernet-encrypted raw secret — mirrors Connection._database_url pattern
    _secret_key = models.TextField(db_column='secret_key')
    # blank=True: no rules required at creation; Django auto-creates the join table
    rules = models.ManyToManyField(
        'Rule',
        blank=True,
        related_name='dbt_integrations',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('user', 'job_id')]

    def __str__(self):
        return f'{self.name} (job: {self.job_id})'

    def set_secret_key(self, raw: str) -> None:
        """Encrypt and store the raw secret key using Fernet (same pattern as Connection)."""
        f = _get_fernet()
        if f:
            self._secret_key = f.encrypt(raw.encode()).decode()
        else:
            self._secret_key = raw

    def get_secret_key(self) -> str:
        """Decrypt and return the raw secret key."""
        f = _get_fernet()
        if f:
            try:
                return f.decrypt(self._secret_key.encode()).decode()
            except Exception:
                return self._secret_key
        return self._secret_key


class UserProfile(models.Model):
    """Per-user settings — currently stores notification_mode."""

    class NotificationMode(models.TextChoices):
        IMMEDIATE = 'immediate', 'Immediate (one email per rule failure)'
        DIGEST    = 'digest',    'Digest (one email per run)'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    notification_mode = models.CharField(
        max_length=20,
        choices=NotificationMode.choices,
        default=NotificationMode.IMMEDIATE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'UserProfile(user={self.user_id}, mode={self.notification_mode})'


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def _create_user_profile(sender, instance, created, **kwargs):
    """Auto-create a UserProfile with default immediate mode when a User is saved."""
    UserProfile.objects.get_or_create(user=instance)


class ApiKey(models.Model):
    """Named API key for a user, stored as SHA-256 hash; raw key never persisted."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='api_keys',
    )
    name = models.CharField(max_length=100)
    key_hash = models.CharField(max_length=64, unique=True)  # SHA-256 hex, 64 chars
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)  # updated on each auth
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('user', 'name')]

    def __str__(self):
        return f'{self.name} ({self.user})'
