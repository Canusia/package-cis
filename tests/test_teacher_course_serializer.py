from django.test import TestCase

from cis.serializers.highschool import TeacherCourseSerializer


class TeacherCourseSerializerFieldsTest(TestCase):
    def test_serializer_exposes_renewal_fields(self):
        fields = TeacherCourseSerializer().get_fields()
        for name in ('expires_on', 'renewal_required_by',
                     'last_renewed_on', 'renewal_due_date'):
            self.assertIn(name, fields)
