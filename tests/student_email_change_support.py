"""Shared fixtures for the student email change tests (#79).

The view is mounted by tenants inside their own ``student`` URLconf and extends
their student-portal base template, neither of which cis owns. The view tests
therefore run against ``cis.tests.student_email_change_urls`` and stub the two
tenant templates through a locmem loader, so they exercise cis's view and not
any one tenant's portal gates or layout.
"""
import copy
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from cis.models.student import Student

User = get_user_model()

PASSWORD = 'pw-12345!'

STUB_TEMPLATES = {
    'student/base_student.html': (
        '{% block page_header %}{% endblock %}'
        '{% include "cis/messages.html" %}'
        '{% block content %}{% endblock %}'
    ),
    'student/partials/_breadcrumb.html': '<nav>{{ page_name }}</nav>',
    'cis_test/profile_stub.html': '{% include "cis/messages.html" %}PROFILE {{ user.email }}',
}


def make_student(email=None, password=PASSWORD):
    Group.objects.get_or_create(name='student')
    email = (email or f'{uuid.uuid4().hex[:8]}@example.com').lower()
    user = User.objects.create_user(
        username=email, email=email, password=password,
        first_name='Stu', last_name='Dent', psid=uuid.uuid4().hex[:10],
    )
    user.groups.add(Group.objects.get(name='student'))
    return Student.objects.create(user=user, meta={})


def templates_with_stubs():
    """settings.TEMPLATES with STUB_TEMPLATES ahead of the normal loaders."""
    templates = copy.deepcopy(settings.TEMPLATES)
    django_tpl = next(t for t in templates
                      if t['BACKEND'] == 'django.template.backends.django.DjangoTemplates')
    options = django_tpl.setdefault('OPTIONS', {})
    loaders = options.get('loaders') or [
        'django.template.loaders.filesystem.Loader',
        'django.template.loaders.app_directories.Loader',
    ]
    django_tpl['APP_DIRS'] = False
    options['loaders'] = [('django.template.loaders.locmem.Loader', STUB_TEMPLATES)] + list(loaders)
    return templates
