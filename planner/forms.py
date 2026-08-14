from django import forms

from .models import EngineerSettings, Job


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = [
            'reference',
            'location',
            'appointment_type',
            'notes',
        ]
        widgets = {
            'reference': forms.TextInput(
                attrs={
                    'class': 'input',
                    'placeholder': 'TT / job number (optional)',
                }
            ),
            'location': forms.TextInput(
                attrs={
                    'class': 'input',
                    'placeholder': 'e.g. WF16 9PF 22 — or full address',
                    'autofocus': True,
                }
            ),
            'appointment_type': forms.Select(attrs={'class': 'input'}),
            'notes': forms.Textarea(
                attrs={
                    'class': 'input',
                    'rows': 2,
                    'placeholder': 'Optional notes',
                }
            ),
        }


class AppointmentTypeForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ['appointment_type']
        widgets = {
            'appointment_type': forms.Select(attrs={'class': 'input input-compact'}),
        }


class JobNotesForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ['notes']
        widgets = {
            'notes': forms.Textarea(
                attrs={
                    'class': 'input input-notes',
                    'rows': 2,
                    'placeholder': 'Add a note…',
                }
            ),
        }


class SettingsForm(forms.ModelForm):
    class Meta:
        model = EngineerSettings
        fields = ['start_label', 'start_location']
        widgets = {
            'start_label': forms.TextInput(
                attrs={'class': 'input', 'placeholder': 'Home / Depot'}
            ),
            'start_location': forms.TextInput(
                attrs={
                    'class': 'input',
                    'placeholder': 'Your start postcode or address',
                }
            ),
        }
