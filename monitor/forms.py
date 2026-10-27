from django import forms

from .models import Connection, Rule


class ConnectionForm(forms.ModelForm):
    database_url = forms.CharField(
        widget=forms.PasswordInput(
            attrs={'class': 'form-control', 'placeholder': 'postgresql://user:password@host:5432/dbname'},
            render_value=False,
        ),
        label='Database URL',
        help_text='Connection string to your PostgreSQL database. Never stored in plain text.',
    )

    class Meta:
        model = Connection
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. production, staging'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional description'}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.set_database_url(self.cleaned_data['database_url'])
        if commit:
            instance.save()
        return instance


class RuleForm(forms.ModelForm):
    class Meta:
        model = Rule
        fields = ['name', 'schema_name', 'table_name', 'connection', 'rule_type', 'custom_sql', 'timestamp_column', 'max_age_hours', 'min_row_count', 'schedule_time']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'schema_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'public'}),
            'table_name': forms.TextInput(attrs={'class': 'form-control'}),
            'connection': forms.Select(attrs={'class': 'form-select'}),
            'rule_type': forms.RadioSelect(attrs={'class': 'rule-type-radio'}),
            'custom_sql': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'SELECT COUNT(*) > 0 FROM public.orders WHERE created_at > NOW() - INTERVAL \'1 hour\'',
                'style': 'font-family: JetBrains Mono, monospace; font-size: 0.82rem;',
            }),
            'timestamp_column': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'updated_at'}),
            'max_age_hours': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'min_row_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'schedule_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['connection'].required = False
        self.fields['connection'].empty_label = '— Default (env MONITORED_DATABASE_URL)'

    def clean(self):
        cleaned = super().clean()
        rule_type = cleaned.get('rule_type', 'volume_freshness')

        if rule_type == 'custom_sql':
            sql = (cleaned.get('custom_sql') or '').strip()
            if not sql:
                raise forms.ValidationError('Custom SQL is required for this rule type.')
            import re
            if not re.match(r'^\s*SELECT\b', sql, re.IGNORECASE):
                raise forms.ValidationError('Custom SQL must start with SELECT.')
            if re.search(r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b', sql, re.IGNORECASE):
                raise forms.ValidationError('Custom SQL contains forbidden keywords.')
        else:
            timestamp_column = cleaned.get('timestamp_column', '').strip()
            max_age_hours = cleaned.get('max_age_hours')
            min_row_count = cleaned.get('min_row_count')

            has_freshness = bool(timestamp_column) and max_age_hours is not None
            has_volume = min_row_count is not None

            if not has_freshness and not has_volume:
                raise forms.ValidationError(
                    'Rule must have at least one condition: '
                    'freshness (column + max age) or volume (min row count).'
                )
            if bool(timestamp_column) != (max_age_hours is not None):
                raise forms.ValidationError(
                    'Timestamp column and max age must be provided together.'
                )

        return cleaned
