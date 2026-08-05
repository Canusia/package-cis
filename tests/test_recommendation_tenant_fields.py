"""Recommendation data must follow the tenant's vocabulary, not a fixed list.

The recommendation *form* was moved behind `get_tenant_service(
'recommendation_form')`, but three consumers of the same data still hardcoded
one tenant's Pennsylvania field names (Keystone Exam, PSSA, GEIP):

* `StudentRecommendation`'s fixed properties,
* `StudentRecommendationSerializer`'s declared fields,
* the `recommendation_export` report's column map.

A tenant with a different rec form therefore got permanently-empty columns in
the export CE staff actually run, dead fields in the DRF payload, and no way to
surface its own answers without editing `cis`. See ewu#49.

These tests drive everything through `cis.tests.fake_tenant`, whose rec form
declares names no real tenant uses, so they assert the mechanism rather than
any tenant's vocabulary (the lesson of ewu#42).
"""
import types
from unittest import mock

from django import forms
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from cis.models import CustomUser
from cis.models.student import Student, StudentRecommendation
from cis.models.term import AcademicYear, Term

FAKE_TENANT = 'cis.tests.fake_tenant'


class RecommendationAttributeAccessTests(TestCase):
    """A stored answer is readable as an attribute whatever it is called.

    Templates, the serializer and `get_field()` in the export all reach
    recommendation data by attribute, so a tenant field with no matching
    property on the model was simply unreachable -- which is why SCCC's
    templates read `{{ rec.recommendation.student_frl }}` out of the raw blob.
    """

    def setUp(self):
        Group.objects.get_or_create(name='student')
        u = CustomUser.objects.create_user(
            username='s', email='s@example.com', password='x')
        self.student = Student.objects.create(user=u)
        ay = AcademicYear.objects.create(name='AY')
        self.term = Term.objects.create(
            academic_year=ay, code='F25', label='Fall')

    def _rec(self, payload):
        return StudentRecommendation.objects.create(
            student=self.student, term=self.term, recommendation=payload)

    def test_stored_key_is_readable_as_an_attribute(self):
        rec = self._rec({'counselor_marker': 'yes'})

        self.assertEqual(rec.counselor_marker, 'yes')

    def test_unknown_name_still_raises_attribute_error(self):
        """The fallback must not turn every typo into a silent empty string --
        Django, DRF and the template engine all probe for attributes that are
        legitimately absent."""
        rec = self._rec({'counselor_marker': 'yes'})

        with self.assertRaises(AttributeError):
            rec.no_such_field_anywhere

    def test_declared_properties_still_win_over_the_blob(self):
        """`bridge_academy` maps '2' to 'No'; the raw value must not shadow
        it."""
        rec = self._rec({'student_bridge': '2', 'bridge_academy': 'RAW'})

        self.assertEqual(rec.bridge_academy, 'No')

    def test_model_internals_are_untouched(self):
        """Guard: a __getattr__ on a Django model that answers for private or
        dunder names breaks deferred loading, pickling and copy."""
        rec = self._rec({'counselor_marker': 'yes'})

        with self.assertRaises(AttributeError):
            rec._some_private_thing


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class RecommendationExportFieldsTests(TestCase):
    def test_fields_come_from_the_tenant_form(self):
        from cis.services.recommendation_fields import recommendation_export_fields

        fields = recommendation_export_fields()

        self.assertIn('counselor_marker', fields)
        self.assertIn('local_assessment', fields)

    def test_labels_come_from_the_tenant_form(self):
        from cis.services.recommendation_fields import recommendation_export_fields

        fields = recommendation_export_fields()

        self.assertEqual(fields['counselor_marker'], 'Counselor Marker')

    def test_structural_fields_are_not_exported(self):
        """`student`, `term`, `upload_label` and friends are plumbing, and the
        export already carries student and term columns of its own."""
        from cis.services.recommendation_fields import recommendation_export_fields

        fields = recommendation_export_fields()

        for name in ('student', 'term', 'student_state_id', 'upload_label',
                     'upload'):
            self.assertNotIn(name, fields)

    def test_another_tenants_vocabulary_is_absent(self):
        """The point of the change: no tenant carries another's fields."""
        from cis.services.recommendation_fields import recommendation_export_fields

        fields = recommendation_export_fields()

        for name in ('keystone_exam', 'geip', 'enrolled_in_honors'):
            self.assertNotIn(name, fields)


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class RecommendationExportReportTests(TestCase):
    def test_report_columns_follow_the_tenant_form(self):
        from cis.reports.recommendation_export import recommendation_export

        headers = recommendation_export().column_map()

        self.assertIn('Counselor Marker', headers.values())
        self.assertNotIn('Keystone Exam', headers.values())

    def test_report_keeps_its_identity_columns(self):
        from cis.reports.recommendation_export import recommendation_export

        headers = recommendation_export().column_map()

        for label in ('Canusia ID Number', 'Student Legal First Name',
                      'High School', 'Term Code', 'Submitted On'):
            self.assertIn(label, headers.values())


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class RecommendationSerializerTests(TestCase):
    """The DRF payload carried five hardcoded Pennsylvania fields and none of
    the tenant's own, so a tenant's CE DataTable had nothing to bind to."""

    def setUp(self):
        Group.objects.get_or_create(name='student')
        u = CustomUser.objects.create_user(
            username='ser', email='ser@example.com', password='x')
        self.student = Student.objects.create(user=u)
        ay = AcademicYear.objects.create(name='AY-ser')
        self.term = Term.objects.create(
            academic_year=ay, code='F26', label='Fall 26')
        self.rec = StudentRecommendation.objects.create(
            student=self.student, term=self.term,
            recommendation={'counselor_marker': 'yes',
                            'local_assessment': 'Passed'})

    def _data(self):
        from cis.serializers.student import StudentRecommendationSerializer
        return StudentRecommendationSerializer(self.rec).data

    def test_payload_carries_the_tenant_fields(self):
        data = self._data()

        self.assertEqual(data.get('counselor_marker'), 'yes')
        self.assertEqual(data.get('local_assessment'), 'Passed')

    def test_payload_drops_another_tenants_vocabulary(self):
        data = self._data()

        for name in ('keystone_exam', 'geip', 'enrolled_in_honors'):
            self.assertNotIn(name, data)


class ExplicitExportFieldsTests(TestCase):
    """A tenant can name its own export columns.

    Derived labels come from the form, and a form label is a question put to a
    counselor -- "Qualifies for Gifted Education Individual Program (GEIP)
    (dropdown)" is a fine prompt and a terrible CSV header. A tenant that cares
    about its export exports `export_fields()` and gets exactly the columns and
    headers it asks for.
    """

    def _stub_service(self, **attrs):
        module = types.ModuleType('stub_recommendation_form')
        for key, value in attrs.items():
            setattr(module, key, value)
        return module

    def test_explicit_export_fields_are_used_verbatim(self):
        from cis.services import recommendation_fields

        service = self._stub_service(
            export_fields=lambda: {'geip': 'GEIP', 'grade_earned': 'Grade Earned'},
            StudentRecommendationForm=object(),
        )
        with mock.patch.object(recommendation_fields, 'get_tenant_service',
                               return_value=service):
            fields = recommendation_fields.recommendation_export_fields()

        self.assertEqual(fields, {'geip': 'GEIP', 'grade_earned': 'Grade Earned'})

    def test_form_is_used_when_the_tenant_declares_no_export_fields(self):
        from cis.services import recommendation_fields

        class Form:
            base_fields = {'local_assessment': forms.CharField(label='Local')}

        service = self._stub_service(StudentRecommendationForm=Form)
        with mock.patch.object(recommendation_fields, 'get_tenant_service',
                               return_value=service):
            fields = recommendation_fields.recommendation_export_fields()

        self.assertEqual(fields, {'local_assessment': 'Local'})
