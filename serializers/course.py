from rest_framework import serializers
from .highschool_admin import CustomUserSerializer

from ..models.course import (
    Course, Cohort, Category, Campus, Location,
    TechCenter,
    CourseUpload,
    CourseAppRequirement,
)
from ..models.tech_center_staff import TechCenterStaff

class CategorySerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Category
        fields = '__all__'

class TechCenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechCenter
        fields = '__all__'

class TechCenterStaffSerializer(serializers.ModelSerializer):
    #tech_centers = TechCenterSerializer()
    user = CustomUserSerializer()
    tech_centers = TechCenterSerializer(
        many=True,
        read_only=True
    )

    class Meta:
        model = TechCenterStaff
        fields = [
            'id',
            'user',
            'tech_centers'
        ]

        datatables_always_serialize = [
            'tech_centers'
        ]

class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = '__all__'

class CampusSerializer(serializers.ModelSerializer):
    locations = LocationSerializer(many=True)

    class Meta:
        model = Campus
        fields = '__all__'

class CohortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cohort
        fields = '__all__'

class CourseUploadBareBoneSerializer(serializers.ModelSerializer):
    file_name = serializers.CharField()

    class Meta:
        model = CourseUpload
        fields = '__all__'

        datatables_always_serialize = [
            'file_name',
            'id'
        ]
        
class CourseSerializer(serializers.ModelSerializer):
    category = CategorySerializer()
    cohort = CohortSerializer()
    campus = CampusSerializer()
    
    uploads = CourseUploadBareBoneSerializer(many=True)
    syllabi_uploads = CourseUploadBareBoneSerializer(many=True)
    shared_resource_uploads = CourseUploadBareBoneSerializer(many=True)
    
    is_available_for_si = serializers.SerializerMethodField()
    is_available_for_new_schools = serializers.SerializerMethodField()

    sexy_description = serializers.CharField(read_only=True)

    class Meta:
        model = Course
        fields = '__all__'
        
        datatables_always_serialize = [
            'catalog_number',
            'name',
            'sexy_description',
            'id'
        ]

    def get_is_available_for_si(self, obj):
        if not obj.meta:
            return 'No'        
        return 'Yes' if obj.meta.get('available_for_si') == '1' else 'No'

    def get_is_available_for_new_schools(self, obj):
        if not obj.meta:
            return 'No'        
        return 'Yes' if obj.meta.get('available_for_new_schools') == '1' else 'No'


class CourseAppRequirementSerializer(serializers.ModelSerializer):
    course = CourseSerializer()

    class Meta:
        model = CourseAppRequirement
        fields = '__all__'
        ref_name = 'CisCourseAppRequirement'


class CourseUploadSerializer(serializers.ModelSerializer):
    course = CourseSerializer()

    class Meta:
        model = CourseUpload
        fields = '__all__'
