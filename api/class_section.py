"""
External SIS integration endpoint for pushing class section data into MyCE.

Used by Banner and other Student Information Systems to create or update
ClassSection records via a POST-only REST API.  Input validation is delegated
to the ``ClassSectionRow`` pydantic schema (single source of truth for field
rules), while DRF field declarations define the public API contract.
"""

import logging

from django.core.exceptions import MultipleObjectsReturned

from pydantic import ValidationError as PydanticValidationError

from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework import viewsets, status, serializers
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from ..utils import CIS_user_only

from ..models.course import Course
from ..models.highschool import HighSchool
from ..models.term import Term
from ..models.teacher import Teacher
from ..models.section import ClassSection

from ..services.importers.class_section_schema import ClassSectionRow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field-mapping helpers
# ---------------------------------------------------------------------------

# API field names that differ from the pydantic schema field names.
API_TO_SCHEMA_FIELD_MAP = {
    'highschool_course_name': 'highschool_course_title',
}

# Fields accepted by the API but not defined in the pydantic schema.
API_ONLY_FIELDS = {'lab_fees', 'status'}


def _api_payload_to_schema_dict(data: dict) -> dict:
    """Transform a flat API POST body into a dict suitable for
    ``ClassSectionRow.model_validate()``.

    Handles:
    - Renaming API field names to pydantic field names where they differ
    - Stripping API-only fields that pydantic doesn't know about
    - Converting ``status`` (A/C) → ``cancel_flag`` (Y/N)
    - Defaulting the required ``name`` field to the ``term_code`` value
    """
    out = {}
    for key, value in data.items():
        if key in API_ONLY_FIELDS:
            continue
        mapped_key = API_TO_SCHEMA_FIELD_MAP.get(key, key)
        out[mapped_key] = value

    # Convert status A/C → cancel_flag Y/N
    raw_status = data.get('status')
    if raw_status:
        out['cancel_flag'] = 'Y' if raw_status == 'C' else 'N'

    # The pydantic schema requires ``name`` (term name).  The API doesn't
    # send it, so default to the term_code value as a passthrough.
    if 'name' not in out:
        out['name'] = data.get('term_code', '')

    return out


def _schema_field_to_api_name(field: str) -> str:
    """Reverse-map a pydantic field name back to the API field name for error
    responses."""
    reverse = {v: k for k, v in API_TO_SCHEMA_FIELD_MAP.items()}
    return reverse.get(field, field)


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------

class ClassSectionSerializer(serializers.ModelSerializer):
    """DRF serializer for the external ClassSection push API.

    Field declarations define the JSON contract (names, types, sources).
    Validation is delegated to ``ClassSectionRow`` (pydantic) and FK
    resolution is done once in ``validate()``, then reused in ``create()``.
    """

    term_code = serializers.CharField(
        max_length=10,
        source='term.code'
    )

    reference_number = serializers.IntegerField(
        source='class_number'
    )

    section_number = serializers.CharField(
        max_length=5
    )

    start_date = serializers.DateField(
    )
    end_date = serializers.DateField(
    )

    tuition = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00
    )

    lab_fees = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00
    )

    highschool_course_name = serializers.CharField(
        max_length=100
    )

    status = serializers.ChoiceField(
        # possible values are A or C
        choices=ClassSection.CLASS_STATUS
    )

    course_name = serializers.CharField(
        max_length=100,
        source='course.name'
    )

    course_title = serializers.CharField(
        max_length=100,
        source='course.title'
    )

    credit_hours = serializers.IntegerField(
        source='course.credit_hours'
    )

    highschool_ceeb = serializers.CharField(
        max_length=100,
        source='highschool.code'
    )

    teacher_hs_email = serializers.CharField(
        max_length=100,
        source='teacher.user.email'
    )

    registration_term_code = serializers.CharField(
        max_length=10,
        source='registration_term.code'
    )

    class Meta:
        model = ClassSection
        ref_name = 'ApiClassSectionSerializer'  # Set a unique ref_name here
        fields = [
            'id',
            # 'class_number',
            'term_code',
            'reference_number',
            'section_number',

            'start_date',
            'end_date',
            'tuition',
            'lab_fees',
            'course_name',
            'course_title',
            'credit_hours',
            'highschool_ceeb',
            'teacher_hs_email',
            'highschool_course_name',
            'status',
            'registration_term_code'
        ]

    def validate(self, data):
        """Validate incoming data in two phases:

        1. **Pydantic validation** — delegates field-level rules to
           ``ClassSectionRow`` (type coercion, format checks, range rules).
        2. **FK resolution** — resolves Term, RegistrationTerm, HighSchool,
           Teacher, and Course from the database, collecting all errors
           before raising.

        Resolved FK objects are stashed in ``data['_resolved']`` so
        ``create()`` can use them without duplicate queries.
        """
        # -- Phase 1: Pydantic validation against the raw POST payload ------
        raw = self.initial_data
        schema_dict = _api_payload_to_schema_dict(raw)

        try:
            validated_row = ClassSectionRow.model_validate(schema_dict)
        except PydanticValidationError as exc:
            field_errors = {}
            for err in exc.errors():
                loc = err.get('loc', ())
                field = _schema_field_to_api_name(str(loc[0])) if loc else '__all__'
                field_errors.setdefault(field, []).append(err['msg'])
            raise ValidationError(field_errors)

        # -- Phase 2: FK resolution (collect all errors) --------------------
        errors = {}

        # Term
        term = None
        try:
            term = Term.objects.get(code=validated_row.term_code)
        except Term.DoesNotExist:
            errors['term_code'] = ['Term code does not exist.']
        except Term.MultipleObjectsReturned:
            errors['term_code'] = ['Multiple terms found for this code.']

        # Registration Term
        registration_term = None
        try:
            registration_term = Term.objects.get(
                code=validated_row.registration_term_code
            )
        except Term.DoesNotExist:
            errors['registration_term_code'] = [
                'Registration term code does not exist.'
            ]
        except Term.MultipleObjectsReturned:
            errors['registration_term_code'] = [
                'Multiple terms found for this registration term code.'
            ]

        # High School
        highschool = None
        try:
            highschool = HighSchool.objects.get(
                code__iexact=validated_row.highschool_ceeb
            )
        except HighSchool.DoesNotExist:
            errors['highschool_ceeb'] = [
                'High school CEEB code does not exist.'
            ]
        except HighSchool.MultipleObjectsReturned:
            errors['highschool_ceeb'] = [
                'Multiple high schools found for this CEEB code.'
            ]

        # Teacher
        teacher = None
        if validated_row.teacher_hs_email:
            try:
                teacher = Teacher.objects.get(
                    user__email__iexact=validated_row.teacher_hs_email
                )
            except Teacher.DoesNotExist:
                errors['teacher_hs_email'] = ['Teacher does not exist.']

        # Course
        course = None
        try:
            course = Course.objects.get(
                name=validated_row.course_name,
                status__iexact='active'
            )
        except Course.DoesNotExist:
            errors['course_name'] = ['Course does not exist.']
        except MultipleObjectsReturned:
            errors['course_name'] = [
                'Multiple active courses found for this name.'
            ]

        if errors:
            raise ValidationError(errors)

        # -- Stash resolved objects for create() ----------------------------
        data['_resolved'] = {
            'validated_row': validated_row,
            'term': term,
            'registration_term': registration_term,
            'highschool': highschool,
            'teacher': teacher,
            'course': course,
        }

        return data

    def create(self, validated_data):
        """Create or update a ``ClassSection`` using pre-resolved FK objects.

        Reads resolved objects from ``validated_data['_resolved']`` (set by
        ``validate()``) to avoid duplicate database queries.  Handles
        ``lab_fees`` separately since it is an API-only field not in the
        pydantic schema.
        """
        resolved = validated_data.pop('_resolved')
        row = resolved['validated_row']

        # Read the original status value (A/C) from the raw POST payload
        raw_status = self.initial_data.get('status', 'A')

        class_section = ClassSection.update_or_add(
            term=resolved['term'],
            class_number=row.reference_number,
            section_number=row.section_number,
            course=resolved['course'],
            teacher=resolved['teacher'],
            highschool=resolved['highschool'],
            start_date=row.start_date,
            end_date=row.end_date,
            tuition=row.tuition or 0,
            highschool_course_name=row.highschool_course_title or '',
            status=raw_status,
            registration_term=resolved['registration_term'],
        )

        # Handle lab_fees (API-only field, not in pydantic schema)
        raw_lab_fees = self.initial_data.get('lab_fees')
        if raw_lab_fees:
            try:
                lab_fees_value = float(raw_lab_fees)
            except (TypeError, ValueError):
                lab_fees_value = 0
            if lab_fees_value:
                class_section.lab_fees = lab_fees_value
                class_section.save()

        return class_section


# ---------------------------------------------------------------------------
# ViewSet
# ---------------------------------------------------------------------------

class ClassSectionViewSet(viewsets.ModelViewSet):
    """POST-only endpoint for external SIS integration (e.g. Banner).

    Creates or updates ``ClassSection`` records pushed from an external
    Student Information System.

    **Endpoint**: ``POST /api/v1/class_section/``

    **Authentication**: Token or Session authentication required.
    **Authorization**: User must belong to the CIS staff group.

    **Request body** (JSON)::

        {
            "term_code": "202410",
            "reference_number": 12345,
            "section_number": "01",
            "start_date": "2024-08-26",
            "end_date": "2024-12-13",
            "tuition": 150.00,
            "lab_fees": 25.00,
            "course_name": "BIO 101",
            "course_title": "Introduction to Biology",
            "credit_hours": 3,
            "highschool_ceeb": "123456",
            "teacher_hs_email": "jsmith@school.edu",
            "highschool_course_name": "AP Biology",
            "status": "A",
            "registration_term_code": "202410"
        }

    **Responses**:

    - ``201 Created`` — section created/updated successfully.
    - ``400 Bad Request`` — per-field validation errors.
    - ``405 Method Not Allowed`` — PUT/PATCH/DELETE are not supported.
    """

    serializer_class = ClassSectionSerializer
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [CIS_user_only]
    http_method_names = ['post', 'head']

    def update(self, request):
        """Reject PUT/PATCH — this endpoint is POST-only."""
        response = {'message': 'Update function is not offered in this path.'}
        return Response(response, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, pk=None):
        """Reject DELETE — this endpoint is POST-only."""
        response = {'message': 'Delete function is not offered in this path.'}
        return Response(response, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def get_queryset(self):
        """Return all ClassSection records (required by DRF ModelViewSet)."""
        return ClassSection.objects.all()
