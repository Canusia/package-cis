# users/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from cis.models.customuser import CustomUser

from django.contrib import messages, auth
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.http import HttpResponseRedirect

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from django.contrib.auth.models import Group

from django_recaptcha.fields import ReCaptchaField



class MyCELoginForm(forms.Form):
    
    useremail = forms.EmailField(
        widget=forms.EmailInput(),
        required=True,
        label='Email',
        help_text=''
    )

    password = forms.CharField(
        widget=forms.PasswordInput(),
        required=True
    )

    def clean_useremail(self):
        data = self.cleaned_data.get('useremail', '')

        return data.lower()

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        req_host = request.get_host()

        # PT-40: only exempt local development from CAPTCHA. Production hosts
        # (e.g. *.canusiaplatform.com) must enforce it. e2e/CI still works via
        # the RECAPTCHA_TESTING shim in settings.
        if '127.0.0.1' not in req_host:
            self.fields['captcha'] = ReCaptchaField(
                label=''
            )

    def save(self, request, failed_login_redirect, logged_redirect):
        data = self.cleaned_data
        email = data.get('useremail')
        password = data.get('password')

        user = auth.authenticate(request=request, username=email, password=password)
        if not user:
            locked = CustomUser.objects.filter(
                email__iexact=email, account_locked=True).exists()
            if locked:
                message = (
                    'Your account is locked after too many failed sign-in '
                    'attempts. Please reset your password or contact support.'
                )
            else:
                message = 'Invalid email/password combination, please try again.'
            messages.add_message(
                request,
                messages.SUCCESS,
                message,
                'list-group-item-danger'
            )
            return HttpResponseRedirect(reverse_lazy(failed_login_redirect))

        if user is not None:
            if user.is_active:
                auth.login(request, user)

        return HttpResponseRedirect(reverse_lazy(logged_redirect))

class CustomUserCreationForm(UserCreationForm):

    class Meta(UserCreationForm):
        model = CustomUser
        fields = ('username', 'email', 'psid')

class CustomUserChangeForm(UserChangeForm):

    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'psid')

class DemoRequestForm(forms.Form):
    
    name = forms.CharField(
        widget=forms.TextInput(),
        label='Your Name'
    )

    email = forms.EmailField(
        widget=forms.EmailInput(),
        required=False,
        help_text='Please use your college/university email'
    )

    message = forms.CharField(
        widget=forms.Textarea,
        label='Message/Note',
        help_text='Briefly describe your program'
    )

    captcha = ReCaptchaField(
        label=''
    )

    def save(self):
        data = self.cleaned_data
        to = [
            'kadaji@gmail.com'
        ]
        subject = 'New Access Request'

        message = 'New Access Request Submitted\r\n'
        message += data['name'] + '\r\n'
        message += data['email'] + '\r\n'
        message += data['message']

        email = EmailMultiAlternatives(
            subject,
            message
        )
        email.to = to
        email.send(fail_silently=False)

        from cis.models.highschool_administrator import HSAdministratorAccessRequest
        from cis.models.highschool import HighSchool
        req = HSAdministratorAccessRequest(
            name=data.get('name'),
            email=data.get('email').lower(),
            highschool=HighSchool.objects.first(),
            message=data.get('message')
        )

        try:
            req.save()
        except Exception as e:
            print(e)

        try:
            user = CustomUser.objects.filter(
                email__iexact=data['email'].lower()
            )

            if not user.exists():
                
                names = data.get('name').split(' ')
                
                campus = {}
                campus['manage_settings'] = True
                campus['manage_staff_accounts'] = False

                user = CustomUser(
                    first_name=names[0],
                    last_name=names[1],
                    email=data.get('email'),
                    username=data.get('email'),
                    is_staff=True,
                    is_active=True,
                    campus=campus
                )

                user.set_password('yR3m7T66u2sr')
                user.save()

                staff_group = Group.objects.get(name='ce')
                user.groups.add(staff_group)
        except Exception as e:
            print(e)


