"""
Pydantic schema for ClassSection CSV import.

Single source of truth for:
- CSV column names and order
- Required vs optional fields
- Type validation and coercion
- Custom validation rules
- DB field mapping metadata
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
from datetime import date


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
    reference_number: int = Field(
        description="CRN / Reference number",
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
    @field_validator('course_name')
    @classmethod
    def course_name_must_have_cohort(cls, v):
        if ' ' not in v:
            raise ValueError("Must contain cohort and catalog (e.g. 'BIO 101')")
        return v

    @field_validator('cancel_flag')
    @classmethod
    def cancel_flag_values(cls, v):
        if v is not None and v.lower() not in ('y', 'n'):
            raise ValueError("Must be 'Y' or 'N'")
        return v

    @field_validator('start_date', 'end_date', mode='before')
    @classmethod
    def parse_date_or_none(cls, v):
        """Treat empty strings as None for optional date fields."""
        if v == '' or v is None:
            return None
        return v

    @field_validator('tuition', mode='before')
    @classmethod
    def parse_tuition_or_default(cls, v):
        """Treat empty strings as 0.0."""
        if v == '' or v is None:
            return 0.0
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
            'date': 'Date (YYYY-MM-DD)',
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
