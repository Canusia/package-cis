"""Tenant extra fields on the table serializers (#114 item 5):
EXTRA_FIELDS in the tenant's services/serializer_fields.py, keyed by model
name, are added to the serializers datatables_serializer() hands out."""
import uuid
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework import serializers

from cis.models.student import Student
from cis.serializers import tables
from cis.serializers.student import StudentSerializer

User = get_user_model()
EXTRA = {'student': {'eduid': serializers.CharField(
    source='meta.eduid', read_only=True, default='')}}


def _with(extra):
    return mock.patch(
        'cis.services.tenant_services.get_tenant_override',
        lambda m, a: extra if (m, a) == ('serializer_fields', 'EXTRA_FIELDS') else None)


def _view(action='list', fmt='datatables'):
    return SimpleNamespace(
        action=action, serializer_class=StudentSerializer,
        request=SimpleNamespace(accepted_renderer=SimpleNamespace(format=fmt)))


class SerializerExtraFieldTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        sfx = uuid.uuid4().hex[:6]
        user = User.objects.create_user(username=f'x_{sfx}', email=f'x_{sfx}@x.com')
        self.student = Student.objects.create(user=user, meta={'eduid': 'E123'})

    def test_no_extra_fields_by_default(self):
        with _with(None):
            cls = tables.datatables_serializer(_view(), tables.SlimStudentRowSerializer)
        self.assertIs(cls, tables.SlimStudentRowSerializer)

    def test_slim_serializer_gets_the_field(self):
        with _with(EXTRA):
            cls = tables.datatables_serializer(_view(), tables.SlimStudentRowSerializer)
            data = cls(self.student).data
        self.assertTrue(issubclass(cls, tables.SlimStudentRowSerializer))
        self.assertEqual(data['eduid'], 'E123')

    def test_full_serializer_gets_it_too(self):
        with _with(EXTRA):
            cls = tables.datatables_serializer(
                _view(fmt='json'), tables.SlimStudentRowSerializer)
            self.assertEqual(cls(self.student).data['eduid'], 'E123')

    def test_other_models_unaffected(self):
        with _with(EXTRA):
            self.assertIs(tables.with_tenant_fields(tables.SlimClassSectionSerializer),
                          tables.SlimClassSectionSerializer)

    def test_the_extended_class_is_reused(self):
        with _with(EXTRA):
            first = tables.with_tenant_fields(StudentSerializer)
            self.assertIs(tables.with_tenant_fields(StudentSerializer), first)
