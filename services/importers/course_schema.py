"""
Pydantic schema for Course CSV import.

Single source of truth for:
- CSV column names and order
- Required vs optional fields
- Type validation and coercion
- Custom validation rules
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional


class CourseRow(BaseModel):
    """Single source of truth for the Course CSV import schema."""

    # --- Required fields ---
    name: str = Field(
        min_length=1, description="Course name (e.g. ENG 101)",
        json_schema_extra={"db_field": "name"}
    )
    subject: str = Field(
        min_length=1, description="Subject designator (cohort lookup/create)",
        json_schema_extra={"db_field": "cohort", "is_lookup": True}
    )
    title: str = Field(
        min_length=1, description="Course title",
        json_schema_extra={"db_field": "title"}
    )

    # --- Optional fields ---
    credits: Optional[float] = Field(
        default=1, description="Credit hours (default: 1)",
        json_schema_extra={"db_field": "credit_hours"}
    )
    status: Optional[str] = Field(
        default="Active", description="Status (Active / Inactive)",
        json_schema_extra={"db_field": "status"}
    )
    course_description: Optional[str] = Field(
        default=None, description="Course description",
        json_schema_extra={"db_field": "description"}
    )
    prereq: Optional[str] = Field(
        default=None, description="Prerequisites",
        json_schema_extra={"db_field": "prereq"}
    )
    teacher_reqs: Optional[str] = Field(
        default=None, description="Teacher requirements",
        json_schema_extra={"db_field": "teacher_requirement"}
    )

    # --- Validators ---
    @field_validator('status', mode='before')
    @classmethod
    def validate_status(cls, v):
        if v is None or v == '':
            return 'Active'
        v = v.capitalize()
        if v not in ('Active', 'Inactive'):
            raise ValueError("Must be 'Active' or 'Inactive'")
        return v

    @field_validator('credits', mode='before')
    @classmethod
    def parse_credits(cls, v):
        if v is None or v == '':
            return 1
        try:
            return float(v)
        except (ValueError, TypeError):
            return 1

    @field_validator('subject', mode='before')
    @classmethod
    def truncate_subject(cls, v):
        """Truncate subject to 9 chars (matching management command logic)."""
        if isinstance(v, str) and len(v) > 9:
            return v[:9]
        return v

    @field_validator('course_description', 'prereq', 'teacher_reqs', mode='before')
    @classmethod
    def empty_string_to_none(cls, v):
        """Treat empty strings as None for optional string fields."""
        if v == '':
            return None
        return v

    @field_validator('name', mode='before')
    @classmethod
    def normalize_spaces(cls, v):
        """Collapse double spaces in course name."""
        if isinstance(v, str):
            return v.replace('  ', ' ')
        return v

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
