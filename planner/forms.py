from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .models import EngineerSettings, Job, VanKitItem

User = get_user_model()


class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={
                'class': 'input',
                'placeholder': 'Username',
                'autofocus': True,
                'autocomplete': 'username',
            }
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                'class': 'input',
                'placeholder': 'Password',
                'autocomplete': 'current-password',
            }
        ),
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'checkbox'}),
    )


class RegisterForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={
                'class': 'input',
                'placeholder': 'Username',
                'autofocus': True,
                'autocomplete': 'username',
            }
        ),
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(
            attrs={
                'class': 'input',
                'placeholder': 'Password',
                'autocomplete': 'new-password',
            }
        ),
    )
    password2 = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(
            attrs={
                'class': 'input',
                'placeholder': 'Confirm password',
                'autocomplete': 'new-password',
            }
        ),
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'checkbox'}),
    )

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if not username:
            raise forms.ValidationError('Enter a username.')
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('That username is already taken.')
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Passwords do not match.')
        if p1:
            validate_password(p1)
        return cleaned

    def save(self):
        return User.objects.create_user(
            username=self.cleaned_data['username'],
            password=self.cleaned_data['password1'],
        )


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
                    'class': 'input input-caps',
                    'placeholder': 'ADDRESS, POSTCODE, OR BUSINESS — E.G. WF12 8AJ ESSO',
                    'autocapitalize': 'characters',
                    'spellcheck': 'false',
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

    def clean_location(self):
        return (self.cleaned_data.get('location') or '').strip().upper()


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


class VanKitItemForm(forms.ModelForm):
    class Meta:
        model = VanKitItem
        fields = ['name', 'product_code', 'notes']
        widgets = {
            'name': forms.TextInput(
                attrs={
                    'class': 'input',
                    'placeholder': 'Item name',
                }
            ),
            'product_code': forms.TextInput(
                attrs={
                    'class': 'input input-caps',
                    'placeholder': 'Product code',
                    'autocapitalize': 'characters',
                    'spellcheck': 'false',
                }
            ),
            'notes': forms.TextInput(
                attrs={
                    'class': 'input',
                    'placeholder': 'Notes (optional)',
                }
            ),
        }

    def clean_name(self):
        return (self.cleaned_data.get('name') or '').strip()

    def clean_product_code(self):
        code = VanKitItem.normalise_code(self.cleaned_data.get('product_code') or '')
        if not code:
            raise forms.ValidationError('Enter a product code.')
        qs = VanKitItem.objects.filter(product_code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('That product code is already on the list.')
        return code

    def clean_notes(self):
        return (self.cleaned_data.get('notes') or '').strip()


class VanKitBulkForm(forms.Form):
    lines = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'input',
                'rows': 6,
                'placeholder': 'One per line: CODE | Item name\ne.g. ABC123 | Fibre cleaver',
                'spellcheck': 'false',
            }
        ),
        help_text='CODE | Name  or  CODE - Name  (one item per line)',
    )


class VanKitScanForm(forms.Form):
    product_code = forms.CharField(
        max_length=64,
        widget=forms.TextInput(
            attrs={
                'class': 'input input-caps',
                'placeholder': 'Scan / type product code',
                'autofocus': True,
                'autocapitalize': 'characters',
                'spellcheck': 'false',
                'autocomplete': 'off',
            }
        ),
    )

    def clean_product_code(self):
        code = VanKitItem.normalise_code(self.cleaned_data.get('product_code') or '')
        if not code:
            raise forms.ValidationError('Enter a product code.')
        return code


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
