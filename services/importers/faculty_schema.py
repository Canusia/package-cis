"""
Pydantic schema for Faculty CSV import.

Single source of truth for CSV column names/order, required vs optional fields,
type validation/coercion, and the course/role pair columns. Mirrors
instructor_schema.InstructorRow.
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class FacultyRow(BaseModel):
    """Single source of truth for the Faculty CSV import schema."""

    # --- Required identity ---
    email: str = Field(
        min_length=1, description="Email (match key + login)",
        json_schema_extra={"db_field": "email"})
    first_name: str = Field(
        min_length=1, description="First name", json_schema_extra={"db_field": "first_name"})
    last_name: str = Field(
        min_length=1, description="Last name", json_schema_extra={"db_field": "last_name"})

    # --- Optional person fields ---
    psid: Optional[str] = Field(default=None, description="PS ID",
                                json_schema_extra={"db_field": "psid"})
    middle_name: Optional[str] = Field(default=None, description="Middle name",
                                       json_schema_extra={"db_field": "middle_name"})
    secondary_email: Optional[str] = Field(default=None, description="Secondary email",
                                           json_schema_extra={"db_field": "secondary_email"})
    primary_phone: Optional[str] = Field(default=None, description="Primary phone",
                                         json_schema_extra={"db_field": "primary_phone"})
    address1: Optional[str] = Field(default=None, description="Street address",
                                    json_schema_extra={"db_field": "address1"})
    city: Optional[str] = Field(default=None, description="City",
                                json_schema_extra={"db_field": "city"})
    state: Optional[str] = Field(default=None, description="State",
                                 json_schema_extra={"db_field": "state"})
    postal_code: Optional[str] = Field(default=None, description="ZIP / postal code",
                                       json_schema_extra={"db_field": "postal_code"})
    status: Optional[str] = Field(default="Active", description="Faculty status (Active / Inactive)",
                                  json_schema_extra={"db_field": "status"})

    # --- Course / role pair columns (course_1..course_10, role_1..role_10) ---
    course_1: Optional[str] = Field(default=None, description="Course name #1 (matched on Course.name, Active)")
    role_1: Optional[str] = Field(default=None, description="Role for course #1: faculty or visitor")
    course_2: Optional[str] = Field(default=None, description="Course name #2")
    role_2: Optional[str] = Field(default=None, description="Role for course #2")
    course_3: Optional[str] = Field(default=None, description="Course name #3")
    role_3: Optional[str] = Field(default=None, description="Role for course #3")
    course_4: Optional[str] = Field(default=None, description="Course name #4")
    role_4: Optional[str] = Field(default=None, description="Role for course #4")
    course_5: Optional[str] = Field(default=None, description="Course name #5")
    role_5: Optional[str] = Field(default=None, description="Role for course #5")
    course_6: Optional[str] = Field(default=None, description="Course name #6")
    role_6: Optional[str] = Field(default=None, description="Role for course #6")
    course_7: Optional[str] = Field(default=None, description="Course name #7")
    role_7: Optional[str] = Field(default=None, description="Role for course #7")
    course_8: Optional[str] = Field(default=None, description="Course name #8")
    role_8: Optional[str] = Field(default=None, description="Role for course #8")
    course_9: Optional[str] = Field(default=None, description="Course name #9")
    role_9: Optional[str] = Field(default=None, description="Role for course #9")
    course_10: Optional[str] = Field(default=None, description="Course name #10")
    role_10: Optional[str] = Field(default=None, description="Role for course #10")

    # --- Validators ---
    @model_validator(mode='before')
    @classmethod
    def strip_whitespace(cls, data):
        if isinstance(data, dict):
            return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}
        return data

    @field_validator('email', 'secondary_email')
    @classmethod
    def lowercase_email(cls, v):
        return v.lower() if isinstance(v, str) and v else v

    @field_validator('status', mode='before')
    @classmethod
    def validate_status(cls, v):
        if v is None or v == '':
            return 'Active'
        key = str(v).strip().lower()
        mapping = {'active': 'Active', 'inactive': 'Inactive'}
        if key not in mapping:
            raise ValueError("Must be 'Active' or 'Inactive'")
        return mapping[key]

    @field_validator(
        'role_1', 'role_2', 'role_3', 'role_4', 'role_5',
        'role_6', 'role_7', 'role_8', 'role_9', 'role_10', mode='before')
    @classmethod
    def normalize_role(cls, v):
        """Map faculty/visitor (case-insensitive) -> 'Faculty'/'Visitor'; blank -> None.

        Unknown values are NOT rejected here — they pass through (trimmed) so the
        importer can detect and note them per course/role pair without failing the
        whole row.
        """
        if v is None or v == '':
            return None
        value = str(v).strip()
        mapping = {'faculty': 'Faculty', 'visitor': 'Visitor'}
        return mapping.get(value.lower(), value)

    @field_validator(
        'psid', 'middle_name', 'secondary_email', 'primary_phone', 'address1',
        'city', 'state', 'postal_code',
        'course_1', 'course_2', 'course_3', 'course_4', 'course_5',
        'course_6', 'course_7', 'course_8', 'course_9', 'course_10', mode='before')
    @classmethod
    def empty_string_to_none(cls, v):
        return None if v == '' else v

    # --- Utility class methods (used by importer + web UI) ---
    @classmethod
    def csv_headers(cls) -> list[str]:
        return list(cls.model_fields.keys())

    @classmethod
    def required_headers(cls) -> list[str]:
        return [name for name, info in cls.model_fields.items() if info.is_required()]

    @classmethod
    def field_definitions(cls) -> list[dict]:
        fields = []
        for name, info in cls.model_fields.items():
            fields.append({
                'name': name,
                'description': info.description or '',
                'required': info.is_required(),
                'type': 'Text',
            })
        return fields

    @classmethod
    def course_role_pairs(cls) -> list[tuple[str, str]]:
        """Derive (course_N, role_N) pairs from the declared model fields.

        Returns a pair only when BOTH course_N and role_N fields exist, sorted by
        N — so the pair list can never silently drift from the actual fields.
        """
        indices = []
        for name in cls.model_fields:
            if name.startswith('course_'):
                suffix = name[len('course_'):]
                if suffix.isdigit() and f'role_{suffix}' in cls.model_fields:
                    indices.append(int(suffix))
        return [(f'course_{i}', f'role_{i}') for i in sorted(indices)]

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
