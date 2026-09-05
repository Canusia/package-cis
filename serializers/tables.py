"""Narrow serializers for the CE DataTables feeds (issue #67).

drf-datatables trims unused fields in ``DatatablesRenderer._filter_unused_fields()``,
but only at the top level: a nested serializer is kept whole or dropped whole.
So /ce/registrations/ renders 11 columns and shipped 917 JSON keys and 30 KB per
row, because everything it renders lives under class_section, student or term.
/ce/highschools/ is the control -- it renders only flat columns, so its nested
district *is* a top-level field, already gets dropped, and measures 273 B/row.

The serializers here are narrow at every level. Each carries exactly the union
of what its table's column registry (``data-data``) and its render callbacks
(``row.<path>`` in the matching ``*_table.js``) read -- the set frozen in
cis/tests/test_table_serializer_contract.py, which fails if a field goes
missing or a new one is asked for.

Two rules, both learned the hard way:

* **Selected only for a datatables-format list request.** Nine other callers
  fetch /ce/api/registration with format=json, eight fetch class_section and
  five fetch teacher -- exports, tenant services, and the PT authorization
  scoping tests, which assert on the full shape. Those keep the original
  serializer. ``datatables_serializer()`` is the switch.
* **Copy the field *type*, not just the name.** registrations_table.js compares
  has_signed_student_agreement and has_signed_parent_consent to the *string*
  'True' and has_recommendation to 'Yes'; the originals declare them as
  CharField, which str()s a bool. Re-declaring them as BooleanField would ship
  JSON `true` and the badge would silently stop rendering.

One serializer per *feed*, not per table profile: the section tabs on the
course, highschool and instructor detail pages all read the class_section feed,
and the registrations tab on student and section detail reads the registration
feed. Each class carries the union across its feed's profiles.
"""

from rest_framework import serializers


def datatables_serializer(view, slim_class):
    """`slim_class` for a datatables list request, the view's own otherwise."""
    request = getattr(view, 'request', None)
    renderer = getattr(request, 'accepted_renderer', None)
    if (getattr(view, 'action', None) == 'list'
            and getattr(renderer, 'format', None) == 'datatables'):
        return slim_class
    return view.serializer_class


class SlimTableSerializer(serializers.Serializer):
    """Base for the narrowed feed serializers.

    Every declared field is registered in ``Meta.datatables_always_serialize``,
    because this serializer *is* the trim: it already carries exactly what its
    table reads, so drf-datatables must not trim it again. Its
    ``_filter_unused_fields()`` drops any top-level key no rendered column
    names -- which is every field a render callback reads without a matching
    column, the same mechanism behind ewu#72. Left unprotected,
    registrations_table.js loses changed_on, has_recommendation and
    submitted_grade; sections_table.js loses ce_url, co_reqs and
    section_number.

    Generated from ``_declared_fields`` rather than hand-listed so the two
    cannot drift -- the entire point of this module is that the field set is
    stated once.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.Meta = type(
            'Meta', (), {
                'datatables_always_serialize': tuple(cls._declared_fields),
            })


class _Named(SlimTableSerializer):
    """{'name': ...} -- enough for the many `<thing>.name` columns."""
    name = serializers.CharField()


# The user nests are split by what each feed's contract actually names, rather
# than sharing one wide CustomUser shape. Two nestings of four unused fields is
# ~150 B/row on the registration feed, which is the kind of thing this module
# exists to remove.

# `id` is a ReadOnlyField rather than a UUIDField throughout: the pks are not
# all UUIDs -- TeacherCourseCertificate's is an integer -- and a UUIDField
# stringifies it, so the feed would start returning '1' where it returned 1.
# ReadOnlyField passes the model's own value through untouched, which is what
# the originals' ModelSerializer field inference does.

class _UserName(SlimTableSerializer):
    """student.user.* on the registration feed."""
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    psid = serializers.CharField()


class _UserContact(SlimTableSerializer):
    """teacher.user.* on the section, highschool-teacher and teacher-course
    feeds."""
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.CharField()


class SlimStudentSerializer(SlimTableSerializer):
    """Nested under the registration feed: student.user.* and
    student.highschool.name and grade_level."""
    id = serializers.ReadOnlyField()
    ce_url = serializers.CharField()
    grade_level = serializers.CharField()
    user = _UserName()
    highschool = _Named()


class SlimCourseSerializer(SlimTableSerializer):
    id = serializers.ReadOnlyField()
    name = serializers.CharField()
    title = serializers.CharField()
    catalog_number = serializers.CharField()
    # ReadOnlyField, not CharField: credit_hours is a FloatField, and a
    # CharField would ship '1.0' where the feed ships 1.0.
    credit_hours = serializers.ReadOnlyField()
    cohort = serializers.SerializerMethodField()

    def get_cohort(self, obj):
        return {'designator': obj.cohort.designator} if obj.cohort else None


class SlimTeacherSerializer(SlimTableSerializer):
    id = serializers.ReadOnlyField()
    ce_url = serializers.CharField()
    user = _UserContact()


class SlimTermSerializer(SlimTableSerializer):
    code = serializers.CharField()
    label = serializers.CharField()


class SlimCoReqSerializer(SlimTableSerializer):
    """sections_table.js iterates co_reqs and reads these three."""
    class_number = serializers.CharField()
    section_number = serializers.CharField()
    course_name = serializers.SerializerMethodField()

    def get_course_name(self, obj):
        return obj.course.name if obj.course_id else None


class SlimClassSectionSerializer(SlimTableSerializer):
    id = serializers.ReadOnlyField()
    ce_url = serializers.CharField()
    class_number = serializers.CharField()
    section_number = serializers.CharField()
    status = serializers.CharField()
    roster_status = serializers.CharField()
    prereq = serializers.CharField()
    highschool_course_name = serializers.CharField()
    course = SlimCourseSerializer()
    term = SlimTermSerializer()
    registration_term = SlimTermSerializer()
    teacher = SlimTeacherSerializer()
    highschool = _Named()
    co_reqs = SlimCoReqSerializer(many=True)

    # ClassSectionViewSet annotates these (cis/views/section.py), but the same
    # serializer is nested inside the registration feed, whose sections are
    # not annotated -- a plain IntegerField would raise AttributeError there.
    num_students = serializers.SerializerMethodField()
    registered_students = serializers.SerializerMethodField()

    def get_num_students(self, obj):
        return getattr(obj, 'num_students', None)

    def get_registered_students(self, obj):
        return getattr(obj, 'registered_students', None)


class SlimStudentRegistrationSerializer(SlimTableSerializer):
    # Every declaration below is copied from StudentRegistrationSerializer,
    # type and format included. reviewed_on is a CharField there, not a date
    # field; changed_on reads the `status_changed` property; and the two
    # recommendation fields return the strings 'Yes'/'No', which is what
    # registrations_table.js compares against.
    id = serializers.ReadOnlyField()
    ce_url = serializers.CharField(read_only=True)
    status = serializers.CharField()
    status_pretty = serializers.SerializerMethodField()
    pay_type_pretty = serializers.CharField(read_only=True)
    grade = serializers.CharField()
    submitted_grade = serializers.CharField(read_only=True)
    needs_mirroring = serializers.BooleanField()
    created_on = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')
    changed_on = serializers.CharField(source='status_changed')
    reviewed_on = serializers.CharField(read_only=True)

    # CharField, not BooleanField -- the table JS compares these to the
    # string 'True'. See the module docstring.
    has_signed_student_agreement = serializers.CharField(read_only=True)
    has_signed_parent_consent = serializers.CharField(read_only=True)
    needs_recommendation = serializers.SerializerMethodField(read_only=True)
    has_recommendation = serializers.SerializerMethodField(read_only=True)

    student = SlimStudentSerializer()
    class_section = SlimClassSectionSerializer()

    def get_status_pretty(self, obj):
        return obj.get_status

    def get_needs_recommendation(self, obj):
        return 'Yes' if obj.needs_recommendation() else 'No'

    def get_has_recommendation(self, obj):
        return 'Yes' if obj.has_recommendation() else 'No'


class SlimTeacherHighSchoolSerializer(SlimTableSerializer):
    """highschool detail > instructors (the highschool-teacher feed)."""
    id = serializers.ReadOnlyField()
    status = serializers.CharField()
    teacher = SlimTeacherSerializer()
    highschool = _Named()


class SlimTeacherCourseSerializer(SlimTableSerializer):
    """course detail > instructors (the teacher-course feed)."""
    id = serializers.ReadOnlyField()
    status = serializers.CharField()
    course = SlimCourseSerializer()
    teacher_highschool = SlimTeacherHighSchoolSerializer()


# --------------------------------------------------------------------------
# The remaining feeds. Every field is either copied from the original's
# explicit declaration or left as ReadOnlyField, which passes the model's own
# value through the way ModelSerializer's inference does -- guessing a type is
# how '1' ends up where 1 was (see SlimSerializerMatchesTheOriginalTests).
# --------------------------------------------------------------------------

class _UserStudentRow(SlimTableSerializer):
    """user.* on the students table."""
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.CharField()
    psid = serializers.CharField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %I:%M:%S %p')


class _UserStaff(SlimTableSerializer):
    """user.* on the instructors and high-school-administrators tables."""
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.CharField()
    primary_phone = serializers.CharField()
    last_login = serializers.DateTimeField(
        format='%m/%d/%Y %I:%M %p', read_only=True)


class _UserNameOnly(SlimTableSerializer):
    """createdby.* on the notes table."""
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class _StudentRef(SlimTableSerializer):
    """student.* on the notes and supporting-documents tables."""
    ce_url = serializers.CharField()
    user = _UserNameOnly()
    highschool = _Named()


class SlimStudentRowSerializer(SlimTableSerializer):
    """/ce/students/"""
    id = serializers.ReadOnlyField()
    ce_url = serializers.CharField(read_only=True)
    account_verified = serializers.ReadOnlyField()
    application_status = serializers.ReadOnlyField()
    application_status_display = serializers.CharField(
        source='get_application_status_display', read_only=True)
    graduation_date = serializers.ReadOnlyField()
    parent_email = serializers.ReadOnlyField()
    sis_sent_on = serializers.ReadOnlyField()
    user = _UserStudentRow()
    highschool = _Named()


class SlimStudentNoteSerializer(SlimTableSerializer):
    """/ce/students/notes/"""
    id = serializers.ReadOnlyField()
    note = serializers.ReadOnlyField()
    # FileField, not ReadOnlyField: a ReadOnlyField hands the FieldFile itself
    # to the JSON encoder, which tries list(obj) on anything with __getitem__
    # and so reads the file off S3 -- FileNotFoundError for a row whose object
    # is not there, ValueError for one with no file at all.
    media = serializers.FileField(read_only=True)
    createdon = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')
    createdby = _UserNameOnly()
    student = _StudentRef()
    # Only meta.type is read; the rest of the blob is not shipped.
    meta = serializers.SerializerMethodField()

    def get_meta(self, obj):
        return {'type': (obj.meta or {}).get('type')}


class SlimStudentSupportingDocumentSerializer(SlimTableSerializer):
    """/ce/students/support_docs/ and student detail > files."""
    id = serializers.ReadOnlyField()
    description = serializers.ReadOnlyField()
    document_type = serializers.ReadOnlyField()
    status = serializers.ReadOnlyField()
    media = serializers.FileField(read_only=True)   # see SlimStudentNoteSerializer
    uploaded_on = serializers.DateTimeField(format='%m/%d/%Y')
    term = SlimTermSerializer()
    student = _StudentRef()


class SlimHSAdministratorSerializer(SlimTableSerializer):
    id = serializers.ReadOnlyField()
    user = _UserStaff()


class SlimHighSchoolAdministratorSerializer(SlimTableSerializer):
    """/ce/highschool_admins/ (the hs-administrator-position feed)."""
    id = serializers.ReadOnlyField()
    status = serializers.ReadOnlyField()
    hsadmin = SlimHSAdministratorSerializer()
    position = _Named()
    highschool = _Named()


class SlimCourseAdministratorSerializer(SlimTableSerializer):
    """/ce/faculty_coordinators/ and course detail > administrators."""
    id = serializers.ReadOnlyField()
    role = serializers.ReadOnlyField()
    status = serializers.ReadOnlyField()
    faculty_id = serializers.CharField(read_only=True)
    course = _Named()
    user = _UserStaff()


class SlimCourseRowSerializer(SlimTableSerializer):
    """/ce/courses/"""
    id = serializers.ReadOnlyField()
    name = serializers.ReadOnlyField()
    title = serializers.ReadOnlyField()
    status = serializers.ReadOnlyField()
    credit_hours = serializers.ReadOnlyField()
    campus = _Named()
    is_available_for_si = serializers.SerializerMethodField()

    def get_is_available_for_si(self, obj):
        from cis.serializers.course import CourseSerializer
        return CourseSerializer().get_is_available_for_si(obj)


class SlimTeacherRowSerializer(SlimTableSerializer):
    """/ce/instructors/ (the teacher feed)."""
    id = serializers.ReadOnlyField()
    status = serializers.ReadOnlyField()
    user = _UserStaff()


class SlimAccessRequestSerializer(SlimTableSerializer):
    """/ce/highschool_admin/access_requests"""
    id = serializers.ReadOnlyField()
    name = serializers.ReadOnlyField()
    email = serializers.ReadOnlyField()
    status = serializers.ReadOnlyField()
    submittedon = serializers.DateTimeField(format='%Y-%m-%d')
    highschool = _Named()
