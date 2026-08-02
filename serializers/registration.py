from django.urls import reverse, NoReverseMatch
from rest_framework import serializers

from ..models.section import StudentRegistration, StudentDropRequest
from ..models.student import Student
from .course import (
    CourseSerializer, CampusSerializer,
    LocationSerializer
)

from .student import StudentSerializer
from .teacher import TeacherSerializer
from .highschool import HighSchoolSerializer
from .highschool_admin import HSAdministratorSerializer
from .term import TermSerializer
from .class_section import ClassSectionSerializer
from .highschool_admin import CustomUserSerializer


class RegistrationSummarySerializer(serializers.Serializer):
    status = serializers.CharField(allow_null=True)

    created_on = serializers.CharField(source='created_on__date', allow_null=True)
    # student_count = serializers.CharField(allow_null=True)

    course_name = serializers.CharField(source='class_section__course__name', allow_null=True)
    term_code = serializers.CharField(source='class_section__term__code', allow_null=True)
    term_label = serializers.CharField(source='class_section__term__label', allow_null=True)
    term_year = serializers.CharField(source='class_section__term__year', allow_null=True)
    academic_year = serializers.CharField(source='class_section__term__academic_year__name', allow_null=True)
    highschool_name = serializers.CharField(source='student__highschool__name', allow_null=True)
    
    count = serializers.IntegerField()
    
class StudentRegistrationSerializer(serializers.ModelSerializer):
    class_section = ClassSectionSerializer()
    student = StudentSerializer()
    ce_url = serializers.CharField(
        read_only=True
    )
    highschool = HighSchoolSerializer()
    reviewer = HSAdministratorSerializer()
    # status = serializers.CharField(
    #     source='get_status',
    #     read_only=True
    # )
    status_pretty = serializers.SerializerMethodField()
    changed_on = serializers.CharField(
        source='status_changed'
    )
    submitted_grade = serializers.CharField(read_only=True)

    next_step = serializers.CharField(
        read_only=True
    )

    applied_on = serializers.CharField(read_only=True)
    reviewed_on = serializers.CharField(read_only=True)
    pay_type_pretty = serializers.CharField(read_only=True)
    has_signed_parent_consent = serializers.CharField(read_only=True)
    has_signed_student_agreement = serializers.CharField(read_only=True)
    created_on = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')

    needs_recommendation = serializers.SerializerMethodField(read_only=True)
    has_recommendation = serializers.SerializerMethodField(read_only=True)

    submitted_grade = serializers.CharField(read_only=True)

    def get_status_pretty(self, obj):
        return obj.get_status

    def get_needs_recommendation(self, obj):
        return 'Yes' if obj.needs_recommendation() else 'No'

    def get_has_recommendation(self, obj):
        return 'Yes' if obj.has_recommendation() else 'No'
    
    class Meta:
        model = StudentRegistration
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'created_on',
            'student',
            'class_section',
            'status',
            'status_pretty',
            'reviewer',
            'status_changed_on',
            'changed_on',
            'applied_on',
            'reviewed_on',
            'has_signed_student_agreement',
            'has_signed_parent_consent',
            'needs_mirroring',
            'next_step',
            'pay_type_pretty',
            'non_student_pay_amount',
            'needs_recommendation',
            'has_recommendation',
            'submitted_grade',
            'grade',
        ]

class FailedMirrorRegistrationSerializer(serializers.ModelSerializer):
    """Trimmed registration view for the failed-mirror triage page."""

    student_name      = serializers.SerializerMethodField()
    student_psid      = serializers.SerializerMethodField()
    class_section_str = serializers.SerializerMethodField()
    term_code         = serializers.SerializerMethodField()
    last_log_url      = serializers.SerializerMethodField()
    last_log_status   = serializers.SerializerMethodField()
    student_url       = serializers.SerializerMethodField()
    section_url       = serializers.SerializerMethodField()
    status_display    = serializers.SerializerMethodField()
    last_mirror_at    = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')

    class Meta:
        model = StudentRegistration
        fields = [
            'id', 'student_name', 'student_psid', 'student_url',
            'class_section_str', 'section_url', 'term_code',
            'status', 'status_display', 'needs_mirroring', 'last_mirror_at',
            'last_mirror_error', 'last_log_status', 'last_log_url',
        ]
        datatables_always_serialize = fields

    def get_student_name(self, obj):
        u = obj.student.user
        return f'{u.last_name}, {u.first_name}'

    def get_student_psid(self, obj):
        return getattr(obj.student.user, 'psid', '') or ''

    def get_class_section_str(self, obj):
        cs = obj.class_section
        try:
            hs_name = cs.highschool.name if cs.highschool else ''
        except Exception:
            hs_name = ''
        return f'{cs.course.name} / {cs.section_number} @ {hs_name}'.strip()

    def get_term_code(self, obj):
        return obj.class_section.term.code

    def get_status_display(self, obj):
        return obj.get_status

    def get_student_url(self, obj):
        try:
            return reverse('cis:student', kwargs={'record_id': obj.student.id})
        except NoReverseMatch:
            return ''

    def get_section_url(self, obj):
        try:
            return reverse('cis:section', kwargs={'record_id': obj.class_section.id})
        except NoReverseMatch:
            return ''

    def _last_log(self, obj):
        return obj.mirror_logs.order_by('-sent_on').first()

    def get_last_log_url(self, obj):
        log = self._last_log(obj)
        if not log:
            return None
        try:
            return reverse('ethos:ethos_log_detail', kwargs={'pk': log.id})
        except NoReverseMatch:
            return None

    def get_last_log_status(self, obj):
        log = self._last_log(obj)
        return log.response_status if log else None


class PendingSisMirrorRegistrationSerializer(serializers.ModelSerializer):
    """Registrations queued for the next SIS mirror run (preview tab)."""

    student_name      = serializers.SerializerMethodField()
    student_psid      = serializers.SerializerMethodField()
    class_section_str = serializers.SerializerMethodField()
    term_code         = serializers.SerializerMethodField()
    student_url       = serializers.SerializerMethodField()
    section_url       = serializers.SerializerMethodField()
    status_display    = serializers.SerializerMethodField()
    parent_consent    = serializers.SerializerMethodField()
    will_send         = serializers.SerializerMethodField()
    last_mirror_at    = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')

    class Meta:
        model = StudentRegistration
        fields = [
            'id', 'student_name', 'student_psid', 'student_url',
            'class_section_str', 'section_url', 'term_code',
            'status', 'status_display', 'parent_consent', 'will_send',
            'last_mirror_at',
        ]
        datatables_always_serialize = fields

    def get_student_name(self, obj):
        u = obj.student.user
        return f'{u.last_name}, {u.first_name}'

    def get_student_psid(self, obj):
        return getattr(obj.student.user, 'psid', '') or ''

    def get_class_section_str(self, obj):
        cs = obj.class_section
        try:
            hs_name = cs.highschool.name if cs.highschool else ''
        except Exception:
            hs_name = ''
        return f'{cs.course.name} / {cs.section_number} @ {hs_name}'.strip()

    def get_term_code(self, obj):
        return obj.class_section.term.code

    def get_student_url(self, obj):
        try:
            return reverse('cis:student', kwargs={'record_id': obj.student.id})
        except NoReverseMatch:
            return ''

    def get_section_url(self, obj):
        try:
            return reverse('cis:section', kwargs={'record_id': obj.class_section.id})
        except NoReverseMatch:
            return ''

    def get_status_display(self, obj):
        return obj.get_status

    def get_parent_consent(self, obj):
        from student_onboarding.step_registry import get as get_step
        if get_step('parent_consent') is None:
            return 'N/A'
        return 'Received' if obj.has_signed_parent_consent else 'Pending'

    def get_will_send(self, obj):
        return not obj.is_held_for_parent_consent


class StudentDropRequestSerializer(serializers.ModelSerializer):
    student = StudentSerializer()
    registration = StudentRegistrationSerializer()
    created_on = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')
    ce_url = serializers.CharField(
        read_only=True
    )
    
    class Meta:
        model = StudentDropRequest
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'created_on',
            'student',
            'registration',
            'status',
            'note'
        ]