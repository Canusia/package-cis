"""FERPA consent per campus (package-cis#65).

Spec: docs/superpowers/specs/2026-10-08-ferpa-per-campus-design.md
"""
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.models import CustomUser
from cis.models.course import Campus
from cis.models.settings import Setting
from cis.models.student import Student, StudentFerpa
from cis.models.term import AcademicYear, Term

REG_KEY = f'{settings.CAMPUS_CODE_PREFIX}_cis_registrations'


class FerpaFixtureMixin:
    """ewu = the deployment campus (single-campus tests); a/b = two more
    prefixed campuses, named to sort after it, for multi-campus tests."""

    def build(self):
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        prefix = settings.CAMPUS_CODE_PREFIX
        self.ewu = Campus.objects.filter(code__startswith=prefix).order_by('name').first() \
            or Campus.objects.create(name='AAA Deployment', code=prefix)
        sfx = uuid.uuid4().hex[:6]
        self.a = Campus.objects.create(name=f'zz College A {sfx}', code=f'{prefix}_A{sfx}')
        self.b = Campus.objects.create(name=f'zz College B {sfx}', code=f'{prefix}_B{sfx}')
        user = CustomUser.objects.create_user(
            username=f'stu{sfx}', email=f'stu{sfx}@example.com', password='x')
        self.student = Student.objects.create(user=user)

    def term(self, campus, code):
        from contextlib import nullcontext
        from cis.campus_context import campus_context
        with (campus_context(campus) if campus is not None else nullcontext()):
            year = AcademicYear.objects.create(name=f'AY-{uuid.uuid4().hex[:6]}', campus=campus)
            return Term.objects.create(academic_year=year, code=code, label=code)

    def open_terms(self, campus, *terms):
        Setting.objects.update_or_create(
            key=REG_KEY, campus=campus,
            defaults={'value': {'registration_terms': [str(t.id) for t in terms],
                                'active_term': str(terms[0].id)}})
