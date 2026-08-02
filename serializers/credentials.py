from rest_framework import serializers

from cis.models.teacher import TeacherCourseCertificate


class CredentialExpirySerializer(serializers.ModelSerializer):
    # Backed by annotations on the viewset queryset so they are orderable/
    # searchable by the DataTables filter backend (which resolves the column
    # name against the ORM, not the serializer source).
    instructor_name = serializers.CharField(read_only=True)
    highschool_name = serializers.CharField(read_only=True)
    course_name = serializers.CharField(read_only=True)
    renewal_due_date = serializers.DateField(format='%m/%d/%Y', read_only=True)
    expires_on = serializers.DateField(format='%m/%d/%Y', read_only=True)
    renewal_required_by = serializers.DateField(format='%m/%d/%Y', read_only=True)
    last_renewed_on = serializers.DateField(format='%m/%d/%Y', read_only=True)
    teacher_url = serializers.SerializerMethodField()

    class Meta:
        model = TeacherCourseCertificate
        fields = [
            'id', 'instructor_name', 'highschool_name', 'course_name', 'status',
            'renewal_due_date', 'renewal_required_by', 'expires_on',
            'last_renewed_on', 'teacher_url',
        ]
        # The CE credentials_table binds real data-data columns, so the
        # datatables filter backend serializes those on request; only id +
        # teacher_url (used by the action renderer) must always be present.
        datatables_always_serialize = ['id', 'teacher_url']

    def get_teacher_url(self, obj):
        return f'/ce/instructor/{obj.teacher_highschool.teacher.id}'


class CredentialSummarySerializer(serializers.Serializer):
    """Serializes pre-aggregated .values().annotate(count=...) rows.

    The viewset returns dict rows; field names match the grouping keys it
    selected (course__name / teacher_highschool__highschool__name) plus count.
    Unknown keys for a given grouping simply serialize via get_group fallback.
    """
    group = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    count = serializers.IntegerField(read_only=True)

    def get_status(self, obj):
        # Present only in the by-course grouping; empty for by-highschool rows.
        return obj.get('status', '')

    def get_group(self, obj):
        # The viewset aliases the grouping label to `group`; fall back to the
        # raw values() keys for safety.
        return (
            obj.get('group')
            or obj.get('course__name')
            or obj.get('teacher_highschool__highschool__name')
            or ''
        )
