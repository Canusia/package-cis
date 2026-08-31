from django.contrib.auth import get_user_model
from rest_framework import serializers
from cis.services.recommendation_fields import recommendation_export_fields

from ..models.student import (
    Student, StudentAgreement,
    StudentRecommendation,
    ParentConsent,
    StudentCampusID,
    StudentSupportingDocument,
    StudentTuitionAssistance,
    StudentTuitionAssistanceDocument
)

from .term import TermSerializer
from .course import CampusSerializer
from .highschool import HighSchoolSerializer
from .highschool_admin import CustomUserSerializer

from ..models.note import StudentNote

class DanglingStudentSerializer(serializers.ModelSerializer):
    """Accounts in the student group with no Student record.

    Rows are CustomUser, so every field is flat — unlike StudentSerializer,
    whose user fields are nested.
    """
    last_login = serializers.DateTimeField(
        format='%m/%d/%Y %I:%M %p',
        read_only=True
    )
    other_roles = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = [
            'id',
            'first_name',
            'last_name',
            'email',
            'primary_phone',
            'last_login',
            'other_roles',
        ]
        datatables_always_serialize = ['id', 'other_roles']

    def get_other_roles(self, obj):
        return [r for r in obj.get_roles() if r != 'student']


class StudentSerializer(serializers.ModelSerializer):
    user = CustomUserSerializer()
    highschool = HighSchoolSerializer()
    ce_url = serializers.CharField(
        read_only=True
    )
    application_status_display = serializers.CharField(
        source='get_application_status_display',
        read_only=True,
    )

    class Meta:
        model = Student
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'parent_email',
            'application_status',
            'application_status_display',
            'profile_dirty_at',
            'sis_sent_on',
        ]

        
class StudentTuitionAssistanceSerializer(serializers.ModelSerializer):
    term = TermSerializer()
    student = StudentSerializer()
    
    created_on = serializers.DateField(
        format='%m/%d/%Y',
        input_formats=['%m/%d/%Y']
    )
    ce_url = serializers.CharField(read_only=True)

    class Meta:
        model = StudentTuitionAssistance
        fields = '__all__'
    
        datatables_always_serialize = [
            'id',
            'ce_url'
        ]
        

class StudentCampusIDSerializer(serializers.ModelSerializer):
    student = StudentSerializer()
    campus = CampusSerializer()
    
    class Meta:
        model = StudentCampusID
        fields = '__all__'

        datatables_always_serialize = [
            'id'
        ]

class StudentSupportingDocumentSerializer(serializers.ModelSerializer):
    student = StudentSerializer()
    term = TermSerializer()
    uploaded_on = serializers.DateTimeField(format='%m/%d/%Y')

    filename = serializers.CharField()

    class Meta:
        model = StudentSupportingDocument
        fields = '__all__'

class StudentAgreementSerializer(serializers.ModelSerializer):
    student = StudentSerializer()
    term = TermSerializer()
    student_signed_on = serializers.DateField(format='%m/%d/%Y')

    student_signature = serializers.CharField(source='_student_signature')
    
    class Meta:
        model = StudentAgreement
        fields = '__all__'

class RecommendationValueField(serializers.CharField):
    """One answer out of the recommendation blob, by field name.

    Never raises for an answer the counselor left blank or a field added to the
    tenant's form after a record was stored -- both read as ''.
    """

    def get_attribute(self, instance):
        return (getattr(instance, 'recommendation', None) or {}).get(
            self.field_name, '')


class StudentRecommendationSerializer(serializers.ModelSerializer):
    student = StudentSerializer()

    # Cross-tenant aliases, each backed by a property on the model.
    gpa = serializers.CharField(read_only=True)
    meets_prereq = serializers.CharField(read_only=True)
    student_prereq = serializers.CharField(read_only=True)
    qualification = serializers.CharField(read_only=True)
    waiver_approved = serializers.CharField(read_only=True)

    term = TermSerializer()

    submitted_by = CustomUserSerializer()
    submitted_on = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')

    class Meta:
        model = StudentRecommendation
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'gpa',
            'meets_prereq',
            'qualification',
            'waiver_approved',
            'upload',
        ]

    def get_fields(self):
        """Add the tenant's own recommendation answers.

        `school_assessment`, `grade_earned`, `keystone_exam`, `geip` and
        `enrolled_in_honors` used to be declared here outright. They are one
        tenant's Pennsylvania vocabulary, so every other tenant's payload
        carried five permanently-empty fields and none of its own -- which is
        why a tenant's CE DataTable had to read out of the raw `recommendation`
        blob instead. They come back automatically for any tenant whose rec
        form declares them (ewu#49).
        """
        fields = super().get_fields()
        for name in recommendation_export_fields():
            if name not in fields:
                fields[name] = RecommendationValueField(read_only=True)
        return fields

class ParentConsentSerializer(serializers.ModelSerializer):
    student = StudentSerializer()
    term = TermSerializer()

    parent_signed_on = serializers.DateField(format='%m/%d/%Y')
    parent_signature = serializers.CharField(source='_parent_signature')

    class Meta:
        model = ParentConsent
        fields = '__all__'
