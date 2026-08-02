"""
Pydantic schema for HS Member (HSAdministrator) CSV import.

Single source of truth for:
- CSV column names and order
- Required vs optional fields
- Type validation and coercion
- Custom validation rules
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional


class HSMemberRow(BaseModel):
    """Single source of truth for the HS Member CSV import schema.

    Each field defines:
    - type + required/optional (drives validation)
    - description (for UI display)
    """

    # --- Required fields ---
    email: str = Field(
        min_length=1, description="Admin email address",
        json_schema_extra={"db_field": "email"}
    )
    firstname: str = Field(
        min_length=1, description="First name",
        json_schema_extra={"db_field": "first_name"}
    )
    lastname: str = Field(
        min_length=1, description="Last name",
        json_schema_extra={"db_field": "last_name"}
    )
    ceeb: str = Field(
        min_length=1, description="CEEB code(s), comma-separated",
        json_schema_extra={"db_field": "ceeb"}
    )

    # --- Optional fields ---
    phone: Optional[str] = Field(
        default=None, description="Phone number",
        json_schema_extra={"db_field": "primary_phone"}
    )
    fax: Optional[str] = Field(
        default=None, description="Fax number",
        json_schema_extra={"db_field": "fax"}
    )
    middlename: Optional[str] = Field(
        default=None, description="Middle name",
        json_schema_extra={"db_field": "middle_name"}
    )
    salutation: Optional[str] = Field(
        default=None, description="Salutation",
        json_schema_extra={"db_field": "salutation"}
    )
    position_title: Optional[str] = Field(
        default="Primary Contact", description="Position title (default: Primary Contact)",
        json_schema_extra={"db_field": "position_title"}
    )
    status: Optional[str] = Field(
        default="Active", description="Status (Active / Inactive)",
        json_schema_extra={"db_field": "status"}
    )

    # --- Validators ---
    @model_validator(mode='before')
    @classmethod
    def strip_whitespace(cls, data):
        """Trim leading/trailing whitespace from every incoming string value.

        Runs before all field validators so that every field is matched/assigned
        without stray whitespace, and so that a whitespace-only value (e.g. '  ')
        collapses to '' and is then treated as empty/None downstream.
        """
        if isinstance(data, dict):
            return {
                k: v.strip() if isinstance(v, str) else v
                for k, v in data.items()
            }
        return data

    @field_validator('email')
    @classmethod
    def lowercase_email(cls, v):
        return v.lower()

    @field_validator('status', mode='before')
    @classmethod
    def validate_status(cls, v):
        if v is None or v == '':
            return 'Active'
        if v not in ('Active', 'Inactive'):
            raise ValueError("Must be 'Active' or 'Inactive'")
        return v

    @field_validator('position_title', mode='before')
    @classmethod
    def default_position_title(cls, v):
        if v is None or v == '':
            return 'Primary Contact'
        return v

    @field_validator('phone', 'fax', 'middlename', 'salutation', mode='before')
    @classmethod
    def empty_string_to_none(cls, v):
        """Treat empty strings as None for optional string fields."""
        if v == '':
            return None
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
