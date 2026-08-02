import csv, io, logging

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt

from rest_framework.authentication import (
    SessionAuthentication,
    BasicAuthentication,
    TokenAuthentication
)
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework.permissions import IsAuthenticated

from rest_framework import viewsets, status, mixins, serializers
from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from rest_framework.decorators import api_view 
from rest_framework.response import Response

from ..utils import CIS_user_only
from ..serializers.student import StudentSerializer
from ..serializers.highschool_admin import CustomUserSerializer
from ..serializers.highschool import HighSchoolSerializer

logger = logging.getLogger(__name__)

from cis.models.student import (
    Student, StudentSISError
)

from cis.models.section import StudentRegistration

class StudentSISIDSerializer(serializers.ModelSerializer):
    student_id = serializers.CharField(
        source='user.psid'
    )
    errors = serializers.JSONField(
        write_only=True
    )

    class Meta:
        model = Student
        fields = [
            'id',
            'student_id',
            'errors'
        ]

    def update(self, instance, validated_data):
        student = instance

        # student.user.psid = validated_data.get('user').get('psid')

        user = student.user
        user.psid = validated_data.get('user').get('psid')
        
        if student.user.psid == '-1':
            errors = validated_data.get('errors')

            if errors:
                messages = ','.join(errors.get('error_messages'))
                results = errors.get('match_results', {})

                error = StudentSISError(
                    message=messages,
                    match_results=results,
                    student=student
                )
                error.save()

        user.save()
        student.user.save()
        return instance

class StudentSISSerializer(serializers.ModelSerializer):
    user = CustomUserSerializer()
    highschool = HighSchoolSerializer()
    cte = HighSchoolSerializer()

    parent2_name = serializers.CharField(allow_blank=True, allow_null=True)
    parent2_email = serializers.EmailField(allow_blank=True, allow_null=True)
    parent2_phone = serializers.CharField(allow_blank=True, allow_null=True)
    parent2_education_level = serializers.CharField(allow_blank=True, allow_null=True)
    qualify_tuition_assistance = serializers.CharField(allow_blank=True, allow_null=True)
    can_receive_sms = serializers.CharField(allow_blank=True, allow_null=True)
    ssn = serializers.CharField(source='user.ssn', allow_blank=True, allow_null=True)
    cell_phone = serializers.CharField(source='user.primary_phone', allow_blank=True, allow_null=True)

    # race = serializers.SerializerMethodField('get_race_for_student')
    # ethnicity = serializers.SerializerMethodField('get_ethnicity_for_student')

    class Meta:
        model = Student
        fields = '__all__'
        # exclude = ['created_at', 'updated_at', 'account_verified', 'pidm']

    def get_race_for_student(self, obj):
        return obj.ethnicity

    def get_ethnicity_for_student(self, obj):
        return obj.race
    
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

@method_decorator(csrf_exempt, name='dispatch')
class StudentIDViewSet(viewsets.ModelViewSet):
    serializer_class = StudentSISIDSerializer
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [CIS_user_only]
    http_method_names = ['put', 'head']

    def create(self, request):
        response = {'message': 'Create function is not offered in this path.'}
        return Response(response, status=status.HTTP_403_FORBIDDEN)

    def destroy(self, request, pk=None):
        response = {'message': 'Delete function is not offered in this path.'}
        return Response(response, status=status.HTTP_403_FORBIDDEN)

    def get_queryset(self):
        records = Student.objects.all()
        return records


class ClassRegistrationSISSerializer(serializers.ModelSerializer):
    # id = serializers.CharField()

    # needs_mirroring = serializers.BooleanField()
    class Meta:
        model = StudentRegistration
        fields = [
            'id',
            'status'
        ]

    def update(self, instance, validated_data):
        instance.status = validated_data.get('status', instance.status)
        instance.save()
        
        return instance

@method_decorator(csrf_exempt, name='dispatch')
class ClassRegistrationSISViewSet(viewsets.ModelViewSet):
    serializer_class = ClassRegistrationSISSerializer
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [CIS_user_only]
    http_method_names = ['put', 'head']

    def create(self, request):
        response = {'message': 'Create function is not offered in this path.'}
        return Response(response, status=status.HTTP_403_FORBIDDEN)

    def destroy(self, request, pk=None):
        response = {'message': 'Delete function is not offered in this path.'}
        return Response(response, status=status.HTTP_403_FORBIDDEN)

    def get_queryset(self):
        records = StudentRegistration.objects.all()
        return records

@method_decorator(csrf_exempt, name='dispatch')
class StudentSISAPI(viewsets.ReadOnlyModelViewSet):
    """
    Returns a list of all students in the system who do not have an student ID.
    """
    serializer_class = StudentSISSerializer
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        records = Student.objects.filter(
            (Q(user__psid__isnull=True) | Q(user__psid='-') | Q(user__psid='-1')),
            account_verified=True
        )
        return records