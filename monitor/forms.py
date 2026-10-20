from django import forms

from .models import Rule


class RuleForm(forms.ModelForm):
    class Meta:
        model = Rule
        fields = ['name', 'schema_name', 'table_name', 'timestamp_column', 'max_age_hours', 'min_row_count']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'schema_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'public'}),
            'table_name': forms.TextInput(attrs={'class': 'form-control'}),
            'timestamp_column': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'updated_at'}),
            'max_age_hours': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'min_row_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }

    def clean(self):
        cleaned = super().clean()
        timestamp_column = cleaned.get('timestamp_column', '').strip()
        max_age_hours = cleaned.get('max_age_hours')
        min_row_count = cleaned.get('min_row_count')

        has_freshness = bool(timestamp_column) and max_age_hours is not None
        has_volume = min_row_count is not None

        if not has_freshness and not has_volume:
            raise forms.ValidationError(
                'Reguła musi mieć co najmniej jeden warunek: '
                'freshness (kolumna + maks. wiek) lub wolumen (min. liczba wierszy).'
            )

        if bool(timestamp_column) != (max_age_hours is not None):
            raise forms.ValidationError(
                'Kolumna timestampowa i maksymalny wiek muszą być podane razem.'
            )

        return cleaned
