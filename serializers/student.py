from django.contrib.auth import get_user_model
from rest_framework import serializers

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

class StudentRecommendationSerializer(serializers.ModelSerializer):
    student = StudentSerializer()
    gpa = serializers.CharField(read_only=True)
    grade_level = serializers.CharField(read_only=True)
    meets_prereq = serializers.CharField(read_only=True)
    student_prereq = serializers.CharField(read_only=True)
    
    qualification = serializers.CharField(read_only=True)
    waiver_approved = serializers.CharField(read_only=True)
    
    school_assessment = serializers.CharField(read_only=True)
    grade_earned = serializers.CharField(read_only=True)
    keystone_exam = serializers.CharField(read_only=True)
    geip = serializers.CharField(read_only=True)
    enrolled_in_honors = serializers.CharField(read_only=True)

    term = TermSerializer()

    submitted_by = CustomUserSerializer()
    submitted_on = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')

    class Meta:
        model = StudentRecommendation
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'gpa',
            'grade_level',
            'meets_prereq',
            'qualification',
            'waiver_approved',
            'upload',
            'grade_earned'
        ]

class ParentConsentSerializer(serializers.ModelSerializer):
    student = StudentSerializer()
    term = TermSerializer()

    parent_signed_on = serializers.DateField(format='%m/%d/%Y')
    parent_signature = serializers.CharField(source='_parent_signature')

    class Meta:
        model = ParentConsent
        fields = '__all__'
