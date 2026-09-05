"""Trimmed serializers for the CE DataTables feeds (issue #67).

drf-datatables trims unused fields in ``DatatablesRenderer._filter_unused_fields()``,
but only at the **top level**: a nested serializer is kept whole or dropped
whole. That is the entire problem. /ce/registrations/ rendered 11 columns and
shipped 917 JSON keys, because everything it renders lives under class_section,
student or term, where the trim cannot reach. /ce/highschools/ renders only flat
columns, so its nested district *is* a top-level field, already gets dropped,
and measured 289 B/row with nothing to fix.

So these serializers do exactly one thing: **subclass the original and replace
its nested serializers with trimmed ones.** Every scalar field the original
served is still served, at every level, and the renderer goes on trimming the
top level per request as it always did.

The first version of this module (v0.0.26) instead enumerated the fields each
table reads and declared only those. That was wrong in a way worth recording,
because it looked right and shipped: the serializers live in this shared
package while the *columns* live in each tenant's own table registry, so a
field set derived from one tenant's columns silently blanks another tenant's.
It cost `profile_dirty_at` on the dirty-students table, `pay_type` on the
registration detail tab, and `since` on the HS-administrator roles tab, none of
which any test here could have caught, and no tenant could repair from its own
side (package-cis#11). Subclassing removes the whole class of failure: there is
no enumeration to get wrong.

What is dropped is only the handful of *aggregates* that made the payload big
and that no table column can name in a useful way -- a course's three upload
lists, a teacher's active_courses (a list of certificates, each carrying a
whole nested course) and active_highschools, a high school's district object,
a campus's locations. Everything else rides along.

These are bound only for a datatables-format list request: nine callers fetch
/ce/api/registration with format=json, eight fetch class_section and five fetch
teacher -- exports, tenant services, and the PT authorization-scoping tests,
which assert on the full shape. ``datatables_serializer()`` is the switch.
"""

from cis.serializers.class_section import ClassSectionSerializer
from cis.serializers.course import CampusSerializer, CourseSerializer
from cis.serializers.faculty import CourseAdministratorSerializer
from cis.serializers.highschool import (
    HSAdministratorAccessRequestSerializer, HighSchoolAdministratorSerializer,
    HighSchoolSerializer, HighSchoolTeacherSerializer, TeacherCourseSerializer)
from cis.serializers.note import StudentNoteSerializer
from cis.serializers.registration import (
    StudentDropRequestSerializer, StudentRegistrationSerializer)
from cis.serializers.student import (
    StudentSerializer, StudentSupportingDocumentSerializer)
from cis.serializers.teacher import TeacherSerializer


def datatables_serializer(view, slim_class):
    """`slim_class` for a datatables list request, the view's own otherwise."""
    request = getattr(view, 'request', None)
    renderer = getattr(request, 'accepted_renderer', None)
    if (getattr(view, 'action', None) == 'list'
            and getattr(renderer, 'format', None) == 'datatables'):
        return slim_class
    return view.serializer_class


class _Trim:
    """Drop named fields from the serializer this is mixed into.

    Declarative on purpose: `drop_fields` says which aggregates are being
    given up, and every other field -- including one added to the parent
    tomorrow -- flows through untouched.
    """

    drop_fields = ()

    def get_fields(self):
        fields = super().get_fields()
        for name in self.drop_fields:
            fields.pop(name, None)
        return fields


# --------------------------------------------------------------------------
# The nested pieces. Each keeps every scalar its parent had and gives up only
# the aggregate that made it expensive.
# --------------------------------------------------------------------------

class TrimmedCampusSerializer(_Trim, CampusSerializer):
    """Campus without its locations list."""
    drop_fields = ('locations',)

    class Meta(CampusSerializer.Meta):
        ref_name = 'CisTrimmedCampus'


class TrimmedHighSchoolSerializer(_Trim, HighSchoolSerializer):
    """High school without the nested district object."""
    drop_fields = ('district',)

    class Meta(HighSchoolSerializer.Meta):
        ref_name = 'CisTrimmedHighSchool'


class TrimmedCourseSerializer(_Trim, CourseSerializer):
    """Course without the three upload lists.

    `uploads`, `syllabi_uploads` and `shared_resource_uploads` all read the
    same CourseUpload rows and are the single biggest contributor to the
    section and registration payloads.
    """
    drop_fields = ('uploads', 'syllabi_uploads', 'shared_resource_uploads')
    campus = TrimmedCampusSerializer()

    class Meta(CourseSerializer.Meta):
        ref_name = 'CisTrimmedCourse'


class TrimmedTeacherSerializer(_Trim, TeacherSerializer):
    """Teacher without active_courses / active_highschools.

    active_courses is a list of certificates each carrying a whole nested
    course; on the highschool-teacher feed that alone was most of 1 331 JSON
    keys for a four-column table.
    """
    drop_fields = ('active_courses', 'active_highschools')

    class Meta(TeacherSerializer.Meta):
        ref_name = 'CisTrimmedTeacher'


class TrimmedStudentSerializer(StudentSerializer):
    highschool = TrimmedHighSchoolSerializer()

    class Meta(StudentSerializer.Meta):
        ref_name = 'CisTrimmedStudent'


class TrimmedClassSectionSerializer(ClassSectionSerializer):
    course = TrimmedCourseSerializer()
    campus = TrimmedCampusSerializer()
    highschool = TrimmedHighSchoolSerializer()
    teacher = TrimmedTeacherSerializer()

    class Meta(ClassSectionSerializer.Meta):
        ref_name = 'CisTrimmedClassSection'


# --------------------------------------------------------------------------
# The feed serializers. Each is its original with the nests swapped.
# --------------------------------------------------------------------------

class SlimStudentRegistrationSerializer(StudentRegistrationSerializer):
    class_section = TrimmedClassSectionSerializer()
    student = TrimmedStudentSerializer()
    highschool = TrimmedHighSchoolSerializer()

    class Meta(StudentRegistrationSerializer.Meta):
        ref_name = 'CisSlimStudentRegistration'


class SlimStudentDropRequestSerializer(StudentDropRequestSerializer):
    student = TrimmedStudentSerializer()
    registration = SlimStudentRegistrationSerializer()

    class Meta(StudentDropRequestSerializer.Meta):
        ref_name = 'CisSlimStudentDropRequest'


class SlimClassSectionSerializer(TrimmedClassSectionSerializer):
    class Meta(ClassSectionSerializer.Meta):
        ref_name = 'CisSlimClassSection'


class SlimStudentRowSerializer(TrimmedStudentSerializer):
    class Meta(StudentSerializer.Meta):
        ref_name = 'CisSlimStudent'


class SlimTeacherRowSerializer(TrimmedTeacherSerializer):
    class Meta(TeacherSerializer.Meta):
        ref_name = 'CisSlimTeacher'


class SlimCourseRowSerializer(TrimmedCourseSerializer):
    class Meta(CourseSerializer.Meta):
        ref_name = 'CisSlimCourse'


class SlimTeacherHighSchoolSerializer(HighSchoolTeacherSerializer):
    teacher = TrimmedTeacherSerializer()
    highschool = TrimmedHighSchoolSerializer()

    class Meta(HighSchoolTeacherSerializer.Meta):
        ref_name = 'CisSlimHighSchoolTeacher'


class SlimTeacherCourseSerializer(TeacherCourseSerializer):
    course = TrimmedCourseSerializer()
    teacher_highschool = SlimTeacherHighSchoolSerializer()

    class Meta(TeacherCourseSerializer.Meta):
        ref_name = 'CisSlimTeacherCourse'


class SlimStudentNoteSerializer(StudentNoteSerializer):
    student = TrimmedStudentSerializer()

    class Meta(StudentNoteSerializer.Meta):
        ref_name = 'CisSlimStudentNote'


class SlimStudentSupportingDocumentSerializer(
        StudentSupportingDocumentSerializer):
    student = TrimmedStudentSerializer()

    class Meta(StudentSupportingDocumentSerializer.Meta):
        ref_name = 'CisSlimStudentSupportingDocument'


class SlimHighSchoolAdministratorSerializer(HighSchoolAdministratorSerializer):
    highschool = TrimmedHighSchoolSerializer()

    class Meta(HighSchoolAdministratorSerializer.Meta):
        ref_name = 'CisSlimHighSchoolAdministrator'


class SlimCourseAdministratorSerializer(CourseAdministratorSerializer):
    course = TrimmedCourseSerializer()

    class Meta(CourseAdministratorSerializer.Meta):
        ref_name = 'CisSlimCourseAdministrator'


class SlimAccessRequestSerializer(HSAdministratorAccessRequestSerializer):
    highschool = TrimmedHighSchoolSerializer()

    class Meta(HSAdministratorAccessRequestSerializer.Meta):
        ref_name = 'CisSlimHSAdministratorAccessRequest'
