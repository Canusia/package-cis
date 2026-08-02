from rest_framework import serializers



from ..models.section import ClassSection, ClassSectionSyllabi
from .course import (
    CourseSerializer, CampusSerializer,
    LocationSerializer
)
from .highschool import HighSchoolSerializer, CustomUserSerializer
from .teacher import TeacherSerializer, TeacherCourseCertificateSerializer
from .term import TermSerializer, AcademicYearSerializer

import importlib.util
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.models import FutureCourse, FutureSection, FutureProjection
else:
    from future_sections.models import FutureCourse, FutureSection, FutureProjection

class FutureProjectionSerializer(serializers.ModelSerializer):

    academic_year = AcademicYearSerializer()
    highschool = HighSchoolSerializer()

    created_by = CustomUserSerializer()
    started_on = serializers.DateField(
        format='%m/%d/%Y'
    )
    confirmed_administrators = serializers.CharField(
        read_only=True
    )
    confirmed_class_sections = serializers.CharField(
        read_only=True
    )
    confirmed_choice_class_sections = serializers.CharField(
        read_only=True
    )
    confirmed_facilitator_class_sections = serializers.CharField(
        read_only=True
    )
    meta = serializers.JSONField()
    class Meta:
        model = FutureProjection
        fields = '__all__'


class FutureCourseSerializer(serializers.ModelSerializer):

    term = TermSerializer()
    academic_year = AcademicYearSerializer()
    teacher_course = TeacherCourseCertificateSerializer()
    started_on = serializers.DateField(
        format='%m/%d/%Y'
    )

    class Meta:
        model = FutureCourse
        fields = '__all__'

class FutureSectionSerializer(serializers.ModelSerializer):
    future_course = FutureCourseSerializer()

    class Meta:
        model = FutureSection
        fields = '__all__'



class ClassSectionSyllabiBareBoneSerializer(serializers.ModelSerializer):
    
    filename = serializers.CharField()
    class Meta:
        model = ClassSectionSyllabi
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'filename',
        ]

class ClassSectionCoReqSerializer(serializers.ModelSerializer):

    course_name = serializers.SerializerMethodField()
    def get_course_name(self, obj):
        return obj.course.name
    
    course_credits = serializers.SerializerMethodField()
    def get_course_credits(self, obj):
        return obj.course.credit_hours
    
    class Meta:
        model = ClassSection
        fields = [
            'course_name',
            'section_number',
            'course_credits',
            'class_number'
        ]
    
class ClassSectionSerializer(serializers.ModelSerializer):
    # from class_visit.serializers import VisitScheduleSerializer

    course = CourseSerializer()
    campus = CampusSerializer()
    highschool = HighSchoolSerializer()

    # visit_schedule = VisitScheduleSerializer(many=True)

    co_reqs = ClassSectionCoReqSerializer(many=True)

    syllabi = ClassSectionSyllabiBareBoneSerializer(many=True)

    syllabi_links = serializers.ListField()

    location = LocationSerializer()
    term = TermSerializer()
    registration_term = TermSerializer()
    teacher = TeacherSerializer()

    start_date = serializers.DateField(
        format='%m/%d/%Y'
    )
    end_date = serializers.DateField(
        format='%m/%d/%Y'
    )
    ce_url = serializers.CharField(
        read_only=True
    )

    num_students = serializers.IntegerField(
        read_only=True
    )
    registered_students = serializers.IntegerField(
        read_only=True
    )
    schedule = serializers.CharField(read_only=True)
    has_visit_to_other_section = serializers.CharField(read_only=True)
    
    num_students = serializers.IntegerField(
        read_only=True
    )
    applied_students = serializers.IntegerField(
        read_only=True
    )
    registered_students = serializers.IntegerField(
        read_only=True
    )
    start_time = serializers.SerializerMethodField()
    def get_start_time(self, obj):
        if obj.start_time == 0:
            return '12:00AM'

        import time
        return time.strftime('%I:%M%p', time.strptime(str(obj.start_time), '%H%M'))
    
    is_a_co_req = serializers.CharField(read_only=True)

    end_time = serializers.SerializerMethodField()
    def get_end_time(self, obj):
        if obj.end_time == 0:
            return '12:00AM'

        import time
        return time.strftime('%I:%M%p', time.strptime(str(obj.end_time), '%H%M'))

    class Meta:
        model = ClassSection
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'section_number',
            'class_number',
            'period_time',
            'free_period',
            'course.cohort.designator',
            'course.catalog_number',
            'course.title',
            'course',
            'location',
            'teacher',
            'highschool',
            'credit_hours',
            'prereq',
            'days',
            'start_time',
            'end_time',
            'start_date',
            'end_date',
            'max_enrollment',
            'min_enrollment',
            'enrollment',
            'schedule',
            'ce_url',
            'grade_status',
            'syllabi_status',
            'syllabi_links',
            'co_reqs',
            'is_a_co_req',
            'highschool_course_name',
            'registration_term'
        ]

class ClassSectionSyllabiSerializer(serializers.ModelSerializer):
    class_sections = ClassSectionSerializer(many=True)

    class Meta:
        model = ClassSectionSyllabi
        fields = '__all__'
