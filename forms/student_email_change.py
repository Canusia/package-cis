"""Forms for the student self-service email change (#79)."""
from django import forms


class NewEmailForm(forms.Form):
    new_email = forms.EmailField(
        label='New Email Address',
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}),
    )

    current_password = forms.CharField(
        label='Current Password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),
        strip=False,
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_email(self):
        return self.cleaned_data['new_email'].strip().lower()

    def clean_current_password(self):
        value = self.cleaned_data['current_password']
        if not self.user or not self.user.check_password(value):
            raise forms.ValidationError('Your current password is incorrect.')
        return value


class VerifyCodeForm(forms.Form):
    code = forms.RegexField(
        regex=r'^\s*\d{6}\s*$',
        label='Verification Code',
        error_messages={'invalid': 'Enter the 6-digit code from the email.'},
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'one-time-code', 'maxlength': 6}),
    )
