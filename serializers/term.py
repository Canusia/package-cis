from rest_framework import serializers

from ..models.term import (
    AcademicYear, Term
)
from ..models.course import Campus


class CampusSlimSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campus
        fields = ['id', 'name']


class AcademicYearSerializer(serializers.ModelSerializer):

    class Meta:
        model = AcademicYear
        fields = [
            'id', 'name'
        ]


class AcademicYearListSerializer(serializers.ModelSerializer):
    """AcademicYear rows for the /ce/academic_years/ DataTable, with the
    per-year aggregate counts supplied by AcademicYearViewSet.get_queryset()
    annotations. Kept separate from AcademicYearSerializer so the nested,
    un-annotated use inside TermSerializer isn't forced to resolve them.
    """
    num_sections = serializers.IntegerField(read_only=True)
    num_highschools = serializers.IntegerField(read_only=True)
    num_teachers = serializers.IntegerField(read_only=True)
    num_courses = serializers.IntegerField(read_only=True)
    campus = CampusSlimSerializer(read_only=True)

    class Meta:
        model = AcademicYear
        fields = [
            'id', 'name', 'campus',
            'num_sections', 'num_highschools', 'num_teachers', 'num_courses',
        ]
        datatables_always_serialize = [
            'campus',
            'num_sections', 'num_highschools', 'num_teachers', 'num_courses',
        ]

class TermParentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ['id', 'label']


class TermSerializer(serializers.ModelSerializer):
    academic_year = AcademicYearSerializer()
    parent = TermParentSerializer(read_only=True)
    campus = CampusSlimSerializer(source='academic_year.campus', read_only=True)
    # Aggregate counts supplied by TermViewSet.get_queryset() annotations.
    num_sections = serializers.IntegerField(read_only=True)
    num_highschools = serializers.IntegerField(read_only=True)
    num_teachers = serializers.IntegerField(read_only=True)
    num_courses = serializers.IntegerField(read_only=True)

    class Meta:
        model = Term
        fields = '__all__'
        datatables_always_serialize = [
            'id', 'label', 'parent', 'campus',
            'num_sections', 'num_highschools', 'num_teachers', 'num_courses',
        ]
