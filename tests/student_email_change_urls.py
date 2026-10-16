"""Test URLconf for the student email change view (#79).

Mirrors how a tenant mounts it: inside the ``student`` namespace, next to a
``profile`` page. No tenant portal gates, by design.
"""
from django.shortcuts import render
from django.urls import include, path

from cis.views.student_email_change import change_email


def _profile_stub(request):
    return render(request, 'cis_test/profile_stub.html')


student_patterns = ([
    path('change_email/', change_email, name='change_email'),
    path('profile/', _profile_stub, name='profile'),
], 'student')

urlpatterns = [
    path('student/', include(student_patterns)),
]
