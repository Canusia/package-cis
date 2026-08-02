from django.shortcuts import render, get_object_or_404
from django.conf import settings
from django.contrib import messages, auth

from django.urls import reverse_lazy
from django.http import HttpResponseRedirect
from django.contrib.auth import logout

from cis.menu import cis_menu, draw_menu
from cis.models.teacher import Teacher
from cis.models.course import Course
from cis.models.settings import Setting

from cis.utils import (
    registration_terms, is_student_registration_open
)

def ldap_login(request):
    window_close_notice = Setting.get_value("cis_registrations", "window_close_notice")
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = auth.authenticate(username=username, password=password)
        if not user:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Invalid email/password combination, please try again.',
                'list-group-item-danger')
            return HttpResponseRedirect(reverse_lazy('cis:ldap_login'))

        if user is not None:
            if user.is_active:
                auth.login(request, user)

        return HttpResponseRedirect(reverse_lazy('logged_home'))

    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))

    return render(
        request,
        'cis/index/ldap-login.html',
        {
            'registration_terms': registration_terms(),
            'registration_is_open': is_student_registration_open(),
            'window_close_notice': window_close_notice
        })
ldap_login.login_required = False