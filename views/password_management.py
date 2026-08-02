from django.db.models import Q
from django.contrib import messages
from django.utils.encoding import force_str
from django.utils.translation import gettext as _
from django.http import HttpResponseRedirect, QueryDict
from django.utils.http import urlsafe_base64_decode
from django.contrib.auth import get_user_model
from django.template.response import TemplateResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render, reverse, resolve_url
from django.http import JsonResponse
from django.forms import ValidationError
from django import forms
from django.conf import settings


from django.core.mail import EmailMultiAlternatives
from django.template import loader
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from django.template import Context, Template
from django.template.loader import get_template

from mailer import send_mail, send_html_mail

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from myce.settings import MY_CE
from django.conf import settings

from django.contrib.auth.forms import (
    PasswordResetForm, SetPasswordForm, PasswordChangeForm
)
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site

from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm

from cis.models.customuser import CustomUser

from django_recaptcha.fields import ReCaptchaField

from cis.utils import allowed_to_reset_password, password_reset_email_template

class cisSetPasswordForm(SetPasswordForm):
    def save(self, commit=True):
        user = super().save(commit)

        subject = 'Password Reset'
        to_email = [user.email]

        from cis.settings.password_reset import password_reset as pwd_config
        configs = pwd_config.from_db()

        subject = configs.get('post_password_reset_subject')
        body = Template(configs.get('post_password_reset_email'))

        context = Context({
            'first_name': user.first_name,
            'last_name': user.last_name,
        })
        text_body = body.render(context)

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        if user.secondary_email:
            to_email.append(user.secondary_email)
        
        send_mail(
            subject,
            text_body,
            settings.DEFAULT_FROM_EMAIL,
            to_email
        )

class cisPasswordResetForm(PasswordResetForm):

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if request and not getattr(settings, 'DEBUG'):
            self.fields['captcha'] = ReCaptchaField(
                label=''
            )

    def get_users(self, email):
        active_users = CustomUser.objects.filter(email__iexact=email).all()
        return active_users

    def send_mail(self, subject_template_name, email_template_name,
                  context, from_email, to_email, html_email_template_name=None):
        """
        Sends a django.core.mail.EmailMultiAlternatives to `to_email`.
        """
        subject = loader.render_to_string(subject_template_name, context)

        # Email subject *must not* contain newlines
        subject = ''.join(subject.splitlines())
        body = loader.render_to_string(email_template_name, context)

        email_message = EmailMultiAlternatives(subject, body, from_email, [to_email])
        if html_email_template_name is not None:
            html_email = loader.render_to_string(html_email_template_name, context)
            email_message.attach_alternative(html_email, 'text/html')

        email_message.send()

    def clean(self):
        cd = self.cleaned_data

        try:
            users = self.get_users(self.cleaned_data['email'])
        except:
            users = []

        if len(users) != 1:
            raise ValidationError("Failed while looking up email. Please contact the office for assistance")

        from mailer.models import DontSendEntry
        if DontSendEntry.objects.filter(
            to_address=cd.get('email','').strip().lower()
        ).exists():
            raise ValidationError("We are unable to send password reset link to this email. Please contact the office for assistance")

        user = users[0]
        user_roles = user.get_roles()

        if not allowed_to_reset_password(user_roles):
            raise ValidationError(
                "Unable to send password reset link for the email. Please contact the office for assistance"
            )
        return cd

    def save(self, domain_override=None,
             subject_template_name='cis/password_reset/password_reset_subject.txt',
             email_template_name='cis/password_reset/password_reset_email.html',
             use_https=False, token_generator=default_token_generator,
             from_email=MY_CE.get('default_from'), request=None, html_email_template_name=None,
             extra_email_context=None):

        email_sent_to = []
        email = self.cleaned_data["email"]
        for user in self.get_users(email):
            current_site = get_current_site(request)
            site_name = current_site.name
            domain = current_site.domain

            if not domain.startswith('https://'):
                domain = 'https://' + str(domain)
        
            user_roles = user.get_roles()
            if 'student' in user_roles:
                # Student has not completed part 2 of the student app
                if not user.has_usable_password() or user.psid in ['', None]:
                    student = user.student

                    student.reset_verification_id()
                    student.send_verification_request_email()

                    email_sent_to.append(user.email)
                    continue
                    
            domain = domain.replace('https://', '')
            context = {
                'email': user.email,
                'domain': domain,
                'site_name': site_name,
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'user': user,
                'token': token_generator.make_token(user),
                'protocol': 'https',
            }

            self.send_mail(
                subject_template_name,
                email_template_name,
                context,
                from_email,
                user.email,
                html_email_template_name=None
            )
            email_sent_to.append(user.email)
        return email_sent_to

class cisForceSetPasswordForm(cisSetPasswordForm, forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='force_set_password'
    )

    def __init__(self, user, *args, form_action=None, use_ajax=True, **kwargs):
        super().__init__(user, *args, **kwargs)

        self.helper = FormHelper()
        if use_ajax:
            self.helper.form_class = 'frm_ajax'
        self.helper.disable_csrf = False

        self.helper.form_method = 'POST'
        if form_action:
            self.helper.form_action = str(form_action)

        self.helper.add_input(Submit('submit', 'Update Password'))

    def save(self, user, commit=True):
        data = self.cleaned_data

        user.set_password(data.get('new_password1'))

        user.require_password_reset = False
        user.save()
        return user


def reset_password_complete(request):
    template = "cis/registration/password_reset_complete.html"

    return render(
        request,
        template, {
            'page_title': 'Password Reset Done'})
reset_password_complete.login_required = False

def reset_password(request, uidb64, token):
    token_generator = default_token_generator
    set_password_form = cisSetPasswordForm
    template_name = 'cis/registration/password_reset_confirm.html'

    userModel = get_user_model()
    assert uidb64 is not None and token is not None  # checked by URLconf
    try:
        # urlsafe_base64_decode() decodes to bytestring on Python 3
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = userModel.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, userModel.DoesNotExist):
        user = None

    if user is not None and token_generator.check_token(user, token):
        validlink = True
        title = _('Enter new password')
        if request.method == 'POST':
            form = set_password_form(user, request.POST)
            if form.is_valid():
                form.save()

                user.require_password_reset = False
                user.save()

                post_reset_redirect = reverse('password_reset_complete')
                return HttpResponseRedirect(post_reset_redirect)
        else:
            form = set_password_form(user)
    else:
        validlink = False
        form = None
        title = _('Password reset unsuccessful')

    context = {
        'form': form,
        'title': title,
        'validlink': validlink,
    }

    return TemplateResponse(request, template_name, context)
reset_password.login_required = False

def forgot_password(request):
    template = 'cis/registration/password_reset_form.html'
    password_reset_form = cisPasswordResetForm

    if request.method == "POST":
        form = password_reset_form(request, request.POST)

        if form.is_valid():
            form.save(request=request)
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please check your email for further instructions',
                'list-group-item-success')
        else:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Unable to complete your request. Please contact our office for assistance',
                'list-group-item-danger')
    else:
        form = password_reset_form(request)

    return render(
        request,
        template, {
            'form': form,
            'page_title': 'Reset Password'})
forgot_password.login_required = False
