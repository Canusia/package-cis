"""
Pydantic schema for ClassSection CSV import.

Single source of truth for:
- CSV column names and order
- Required vs optional fields
- Type validation and coercion
- Custom validation rules
- DB field mapping metadata
"""
import functools
import re

from pydantic import (
    BaseModel, Field, ValidationInfo, create_model, field_validator,
    model_validator)
from typing import Optional
from datetime import date

from .validation import coerce_date, import_date_input_formats, import_option


# Tenant knobs for this importer live on the tenant's `class_section_import`
# service module (#114 item 10); every one is optional and defaults to the
# package behaviour. See docs in class_section_importer.ClassSectionImporter.
TENANT_MODULE = 'class_section_import'

# Accepted section date layouts unless settings.IMPORT_DATE_INPUT_FORMATS
# replaces them. ISO first, so well-formed exports stay cheap. Two-digit years
# are rejected unless the tenant sets CLASS_SECTION_IMPORT_ALLOW_2DIGIT_YEAR.
DATE_INPUT_FORMATS = ('%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d')


def course_name_pattern():
    """The tenant's COURSE_NAME_PATTERN, compiled, or None for the package
    rule ("<cohort> <catalog>", split on the first space).

    The pattern's group named `cohort` (else its first group) is the cohort
    designator of a new course, upper-cased. e.g. r'^\\s*([A-Za-z]+)\\s*(\\d.*)$'
    accepts 'BIO 101', 'BIO101' and 'COMM 1030-01'.
    """
    pattern = import_option(TENANT_MODULE, 'COURSE_NAME_PATTERN', None)
    if pattern is None or isinstance(pattern, re.Pattern):
        return pattern
    return re.compile(pattern)


def _is_date_annotation(annotation):
    if annotation is date:
        return True
    return date in getattr(annotation, '__args__', ())


class ClassSectionRow(BaseModel):
    """Single source of truth for the ClassSection CSV import schema.

    Each field defines:
    - type + required/optional (drives validation)
    - description (for UI display)
    - db_field: which ClassSection model field this maps to
    - is_lookup: True if the value needs FK resolution (not a direct assignment)
    """

    # --- Required fields ---
    name: str = Field(
        min_length=1, description="Term name",
        json_schema_extra={"db_field": "term", "is_lookup": True}
    )
    term_code: str = Field(
        min_length=1, description="Term code",
        json_schema_extra={"db_field": "term", "is_lookup": True}
    )
    # str, not int: ClassSection.class_number is a CharField, and int dropped
    # leading zeros and rejected CRNs like '1030-01' (#114 item 10).
    reference_number: str = Field(
        min_length=1, description="CRN / Reference number",
        json_schema_extra={"db_field": "class_number"}
    )
    section_number: str = Field(
        min_length=1, description="Section number",
        json_schema_extra={"db_field": "section_number"}
    )
    course_name: str = Field(
        min_length=1, description="Course name (e.g. 'BIO 101')",
        json_schema_extra={"db_field": "course", "is_lookup": True}
    )
    course_title: str = Field(
        min_length=1, description="Course title",
        json_schema_extra={"db_field": "course", "is_lookup": True}
    )
    registration_term_code: str = Field(
        min_length=1, description="Registration term code",
        json_schema_extra={"db_field": "registration_term", "is_lookup": True}
    )

    # --- Optional fields ---
    highschool_ceeb: Optional[str] = Field(
        default=None, description="High school CEEB code",
        json_schema_extra={"db_field": "highschool", "is_lookup": True}
    )
    teacher_hs_email: Optional[str] = Field(
        default=None, description="Teacher HS email",
        json_schema_extra={"db_field": "teacher", "is_lookup": True}
    )
    roster_verified_on: Optional[str] = Field(
        default=None, description="Roster verified date",
        json_schema_extra={"db_field": None}
    )
    start_date: Optional[date] = Field(
        default=None, description="Section start date (YYYY-MM-DD)",
        json_schema_extra={"db_field": "start_date"}
    )
    end_date: Optional[date] = Field(
        default=None, description="Section end date (YYYY-MM-DD)",
        json_schema_extra={"db_field": "end_date"}
    )
    tuition: Optional[float] = Field(
        default=0.0, description="Tuition amount",
        json_schema_extra={"db_field": "tuition"}
    )
    highschool_course_title: Optional[str] = Field(
        default=None, description="HS course title",
        json_schema_extra={"db_field": "highschool_course_name"}
    )
    credit_hours: Optional[float] = Field(
        default=None, description="Credit hours",
        json_schema_extra={"db_field": "credit_hours"}
    )
    cancel_flag: Optional[str] = Field(
        default=None, description="Cancel flag (Y/N)",
        json_schema_extra={"db_field": "status", "is_lookup": True}
    )

    # --- Validators ---
    @field_validator('reference_number', mode='before')
    @classmethod
    def reference_number_as_text(cls, v):
        """Keep the CRN as typed (an API payload may send a number)."""
        if isinstance(v, int) and not isinstance(v, bool):
            return str(v)
        return v.strip() if isinstance(v, str) else v

    @field_validator('course_name')
    @classmethod
    def course_name_must_have_cohort(cls, v):
        # A tenant COURSE_NAME_PATTERN is checked by the importer, and only
        # when the course is new: an existing course matches by its exact name.
        if course_name_pattern() is None and ' ' not in v:
            raise ValueError("Must contain cohort and catalog (e.g. 'BIO 101')")
        return v

    @field_validator('cancel_flag')
    @classmethod
    def cancel_flag_values(cls, v):
        if v is not None and v.lower() not in ('y', 'n'):
            raise ValueError("Must be 'Y' or 'N'")
        return v

    @field_validator('*', mode='before')
    @classmethod
    def parse_date_or_none(cls, v, info: ValidationInfo):
        """Every date column, including a tenant ROW_SCHEMA's own: blank ->
        None, else any accepted layout (see DATE_INPUT_FORMATS)."""
        field = cls.model_fields.get(info.field_name)
        if field is None or not _is_date_annotation(field.annotation):
            return v
        return coerce_date(
            v, import_date_input_formats(DATE_INPUT_FORMATS),
            allow_2digit_year=bool(import_option(
                TENANT_MODULE, 'CLASS_SECTION_IMPORT_ALLOW_2DIGIT_YEAR', False)),
        )

    @field_validator('tuition', mode='before')
    @classmethod
    def parse_tuition_or_default(cls, v):
        """Strip currency formatting ('$225', '1,200.50'); blank -> 0.0."""
        if v is None:
            return 0.0
        if isinstance(v, str):
            cleaned = v.strip().lstrip('$').replace(',', '').strip()
            return cleaned or 0.0
        return v

    @field_validator('credit_hours', mode='before')
    @classmethod
    def parse_credit_hours_or_none(cls, v):
        """Treat empty strings as None."""
        if v == '' or v is None:
            return None
        return v

    @field_validator('highschool_ceeb', 'teacher_hs_email', 'roster_verified_on',
                     'highschool_course_title', 'cancel_flag', mode='before')
    @classmethod
    def empty_string_to_none(cls, v):
        """Treat empty strings as None for optional string fields."""
        if v == '':
            return None
        return v

    @model_validator(mode='after')
    def start_before_end(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be before end_date")
        return self

    # --- Utility class methods ---

    @classmethod
    def csv_headers(cls) -> list[str]:
        """All CSV column names (for template display and download)."""
        return list(cls.model_fields.keys())

    @classmethod
    def required_headers(cls) -> list[str]:
        """Only required column names."""
        return [name for name, info in cls.model_fields.items() if info.is_required()]

    @classmethod
    def field_definitions(cls) -> list[dict]:
        """Human-friendly field definitions for template display."""
        TYPE_LABELS = {
            'str': 'Text',
            'int': 'Integer',
            'float': 'Decimal',
            'date': 'Date (YYYY-MM-DD or MM/DD/YYYY)',
        }
        fields = []
        for name, info in cls.model_fields.items():
            annotation = info.annotation
            # Unwrap Optional types
            origin = getattr(annotation, '__origin__', None)
            if origin is not None:
                args = [a for a in annotation.__args__ if a is not type(None)]
                type_name = args[0].__name__ if args else 'str'
            else:
                type_name = annotation.__name__
            fields.append({
                'name': name,
                'description': info.description or '',
                'required': info.is_required(),
                'type': TYPE_LABELS.get(type_name, type_name),
            })
        return fields

    @classmethod
    def db_field_mapping(cls) -> dict:
        """Returns {csv_column: db_field} for direct (non-lookup) fields."""
        mapping = {}
        for name, info in cls.model_fields.items():
            extra = info.json_schema_extra or {}
            db_field = extra.get("db_field")
            if db_field and not extra.get("is_lookup"):
                mapping[name] = db_field
        return mapping

    @classmethod
    def lookup_fields(cls) -> dict:
        """Returns {csv_column: db_field} for fields requiring FK resolution."""
        mapping = {}
        for name, info in cls.model_fields.items():
            extra = info.json_schema_extra or {}
            if extra.get("is_lookup"):
                mapping[name] = extra.get("db_field")
        return mapping


# --- Tenant-selected schema -------------------------------------------------

# Columns offered only when the tenant matches teachers by instructor id or
# auto-creates them (TEACHER_MATCH_ORDER / AUTO_CREATE_TEACHER).
INSTRUCTOR_COLUMNS = {
    'instructor_firstname': "Instructor first name (used when auto-creating a new teacher)",
    'instructor_lastname': "Instructor last name (used when auto-creating a new teacher)",
    'instructor_id': "Instructor ID (matched against the user's PSID; stored as PSID on a new teacher)",
}


def _blank_to_none(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


@functools.lru_cache(maxsize=None)
def _with_instructor_columns(base):
    """`base` plus whichever INSTRUCTOR_COLUMNS it does not declare itself."""
    missing = {name: desc for name, desc in INSTRUCTOR_COLUMNS.items()
               if name not in base.model_fields}
    if not missing:
        return base
    fields = {
        name: (Optional[str], Field(default=None, description=desc,
                                    json_schema_extra={"db_field": None}))
        for name, desc in missing.items()
    }
    validators = {
        'instructor_columns_blank_to_none': field_validator(
            *missing, mode='before')(_blank_to_none),
    }
    return create_model(
        base.__name__, __base__=base, __module__=base.__module__,
        __validators__=validators, **fields)


def instructor_columns_enabled():
    order = import_option(TENANT_MODULE, 'TEACHER_MATCH_ORDER', ('email',))
    return (bool(import_option(TENANT_MODULE, 'AUTO_CREATE_TEACHER', False))
            or 'psid' in tuple(order)
            or bool(import_option(TENANT_MODULE, 'BACKFILL_TEACHER_PSID', False)))


def class_section_row_schema():
    """The row schema this tenant imports with.

    The tenant's ROW_SCHEMA (a ClassSectionRow subclass, e.g. adding the
    section due dates) or ClassSectionRow; plus the instructor columns when
    the tenant's teacher-matching knobs use them. Drives the importer, the
    sample file and the import page's column list alike.
    """
    schema = import_option(TENANT_MODULE, 'ROW_SCHEMA', None) or ClassSectionRow
    if instructor_columns_enabled():
        schema = _with_instructor_columns(schema)
    return schema
