from django.db import models
from django.utils import timezone


class Rule(models.Model):
    """Reguła monitoringu dla jednej tabeli PostgreSQL."""

    name = models.CharField(max_length=200, verbose_name='Nazwa reguły')
    schema_name = models.CharField(max_length=100, verbose_name='Schemat')
    table_name = models.CharField(max_length=100, verbose_name='Tabela')

    # Reguła freshness — opcjonalna
    timestamp_column = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Kolumna timestampowa',
        help_text='Nazwa kolumny do sprawdzenia świeżości (opcjonalne)',
    )
    max_age_hours = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Maksymalny wiek rekordu (godz.)',
    )

    # Reguła wolumenu — opcjonalna
    min_row_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Minimalna liczba wierszy',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Reguła'
        verbose_name_plural = 'Reguły'
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
    """Jeden przebieg sprawdzenia wszystkich reguł."""

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Przebieg'
        verbose_name_plural = 'Przebiegi'
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
    """Wynik sprawdzenia jednej reguły w jednym przebiegu."""

    class Status(models.TextChoices):
        OK = 'OK', 'OK'
        FAIL = 'FAIL', 'FAIL'
        ERROR = 'ERROR', 'Błąd'

    run = models.ForeignKey(CheckRun, on_delete=models.CASCADE, related_name='results')
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name='results')
    checked_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=10, choices=Status.choices)

    # Zmierzone wartości
    row_count = models.PositiveIntegerField(null=True, blank=True)
    last_record_age_hours = models.FloatField(null=True, blank=True)

    # Komunikat błędu (gdy status=ERROR)
    error_message = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Wynik reguły'
        verbose_name_plural = 'Wyniki reguł'
        ordering = ['-checked_at']

    def __str__(self):
        return f'{self.rule.name}: {self.status} @ {self.checked_at:%Y-%m-%d %H:%M}'
