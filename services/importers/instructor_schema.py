"""
Pydantic schema for Instructor (Teacher) CSV import.

Single source of truth for CSV column names/order, required vs optional fields,
type validation/coercion, and custom rules.
"""
import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class InstructorRow(BaseModel):
    """Single source of truth for the Instructor CSV import schema."""

    # --- Required identity fields ---
    teacherid: str = Field(
        min_length=1, description="PS ID / match key (CustomUser.psid)",
        json_schema_extra={"db_field": "psid"}
    )
    teacher_id: str = Field(
        min_length=1, description="Netid / login username (CustomUser.username & alt_username)",
        json_schema_extra={"db_field": "username"}
    )
    last_name: str = Field(
        min_length=1, description="Last name",
        json_schema_extra={"db_field": "last_name"}
    )
    first_name: str = Field(
        min_length=1, description="First name",
        json_schema_extra={"db_field": "first_name"}
    )
    primary_email: str = Field(
        min_length=1, description="Primary email (login email)",
        json_schema_extra={"db_field": "email"}
    )
    highschool_ceeb: str = Field(
        min_length=1, description="High school CEEB code (looked up to link the teacher)",
        json_schema_extra={"db_field": "highschool_ceeb", "is_lookup": True}
    )

    # --- Optional person fields ---
    middle_name: Optional[str] = Field(
        default=None, description="Middle name",
        json_schema_extra={"db_field": "middle_name"})
    secondary_email: Optional[str] = Field(
        default=None, description="Secondary email",
        json_schema_extra={"db_field": "secondary_email"})
    home_email: Optional[str] = Field(
        default=None, description="Home/alternate email",
        json_schema_extra={"db_field": "alt_email"})
    status: Optional[str] = Field(
        default="Active", description="Instructor status (Active / Inactive)",
        json_schema_extra={"db_field": "status"})
    home_address: Optional[str] = Field(
        default=None, description="Home street address",
        json_schema_extra={"db_field": "address1"})
    home_city: Optional[str] = Field(
        default=None, description="Home city",
        json_schema_extra={"db_field": "city"})
    home_state: Optional[str] = Field(
        default=None, description="Home state",
        json_schema_extra={"db_field": "state"})
    home_zip: Optional[str] = Field(
        default=None, description="Home ZIP / postal code",
        json_schema_extra={"db_field": "postal_code"})
    cell_phone: Optional[str] = Field(
        default=None, description="Cell phone (primary phone)",
        json_schema_extra={"db_field": "primary_phone"})
    home_phone: Optional[str] = Field(
        default=None, description="Home phone (secondary phone)",
        json_schema_extra={"db_field": "secondary_phone"})
    date_of_birth: Optional[datetime.date] = Field(
        default=None, description="Date of birth (MM/DD/YYYY)",
        json_schema_extra={"db_field": "date_of_birth"})
    date_of_hire: Optional[datetime.date] = Field(
        default=None, description="Date of hire (MM/DD/YYYY) — stored as certificate 'since'",
        json_schema_extra={"db_field": "since"})
    orientation_date: Optional[datetime.date] = Field(
        default=None, description="Orientation date (MM/DD/YYYY)",
        json_schema_extra={"db_field": "orientation_date"})

    # --- Course columns (up to 10) ---
    course_1: Optional[str] = Field(default=None, description="Course name, e.g. 'PHED 150'")
    course_2: Optional[str] = Field(default=None, description="Course name")
    course_3: Optional[str] = Field(default=None, description="Course name")
    course_4: Optional[str] = Field(default=None, description="Course name")
    course_5: Optional[str] = Field(default=None, description="Course name")
    course_6: Optional[str] = Field(default=None, description="Course name")
    course_7: Optional[str] = Field(default=None, description="Course name")
    course_8: Optional[str] = Field(default=None, description="Course name")
    course_9: Optional[str] = Field(default=None, description="Course name")
    course_10: Optional[str] = Field(default=None, description="Course name")

    # --- Validators ---
    @model_validator(mode='before')
    @classmethod
    def strip_whitespace(cls, data):
        """Trim leading/trailing whitespace from every incoming string value.

        Runs before all field validators so that course names and every other
        field are matched/assigned without stray whitespace, and so that a
        whitespace-only value (e.g. '  ') collapses to '' and is then treated
        as empty/None by the downstream validators.
        """
        if isinstance(data, dict):
            return {
                k: v.strip() if isinstance(v, str) else v
                for k, v in data.items()
            }
        return data

    @field_validator('primary_email', 'secondary_email', 'home_email')
    @classmethod
    def lowercase_email(cls, v):
        return v.lower() if isinstance(v, str) and v else v

    @field_validator('status', mode='before')
    @classmethod
    def validate_status(cls, v):
        if v is None or v == '':
            return 'Active'
        if v not in ('Active', 'Inactive'):
            raise ValueError("Must be 'Active' or 'Inactive'")
        return v

    @field_validator(
        'middle_name', 'secondary_email', 'home_email', 'home_address',
        'home_city', 'home_state', 'home_zip', 'cell_phone', 'home_phone',
        'course_1', 'course_2', 'course_3', 'course_4', 'course_5',
        'course_6', 'course_7', 'course_8', 'course_9', 'course_10',
        mode='before')
    @classmethod
    def empty_string_to_none(cls, v):
        if v == '':
            return None
        return v

    @field_validator('date_of_birth', 'date_of_hire', 'orientation_date', mode='before')
    @classmethod
    def parse_mdy_date(cls, v):
        """Accept MM/DD/YYYY (the CSV format) or ISO; blank -> None."""
        if v is None or v == '':
            return None
        if isinstance(v, datetime.date):
            return v
        for fmt in ('%m/%d/%Y', '%Y-%m-%d'):
            try:
                return datetime.datetime.strptime(v.strip(), fmt).date()
            except (ValueError, AttributeError):
                continue
        raise ValueError('Date must be MM/DD/YYYY')

    # --- Utility class methods (used by importer and the web UI) ---

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
            'date': 'Date (MM/DD/YYYY)',
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
    def course_columns(cls) -> list[str]:
        """The CSV columns that hold course names."""
        return [name for name in cls.model_fields if name.startswith('course_')]

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
