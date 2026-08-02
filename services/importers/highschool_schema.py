"""
Pydantic schema for HighSchool CSV import.

Single source of truth for:
- CSV column names and order
- Required vs optional fields
- Type validation and coercion
- Custom validation rules
- DB field mapping metadata
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional

from cis.models.highschool import HighSchool


class HighSchoolRow(BaseModel):
    """Single source of truth for the HighSchool CSV import schema.

    Each field defines:
    - type + required/optional (drives validation)
    - description (for UI display)
    - db_field: which HighSchool model field this maps to
    - is_lookup: True if the value needs FK resolution (not a direct assignment)
    """

    # --- Required fields ---
    name: str = Field(
        min_length=1, description="High school name",
        json_schema_extra={"db_field": "name"}
    )
    code: str = Field(
        min_length=1, description="CEEB code",
        json_schema_extra={"db_field": "code"}
    )

    # --- Optional fields ---
    sau: Optional[str] = Field(
        default=None, description="Building code",
        json_schema_extra={"db_field": "sau"}
    )
    status: Optional[str] = Field(
        default=None, description="Status (Active / Inactive)",
        json_schema_extra={"db_field": "status"}
    )
    district_name: Optional[str] = Field(
        default=None, description="District name (created if not found)",
        json_schema_extra={"db_field": "district", "is_lookup": True}
    )
    address1: Optional[str] = Field(
        default=None, description="Address line 1",
        json_schema_extra={"db_field": "address1"}
    )
    address2: Optional[str] = Field(
        default=None, description="Address line 2",
        json_schema_extra={"db_field": "address2"}
    )
    city: Optional[str] = Field(
        default=None, description="City",
        json_schema_extra={"db_field": "city"}
    )
    state: Optional[str] = Field(
        default=None, description="State",
        json_schema_extra={"db_field": "state"}
    )
    postal_code: Optional[str] = Field(
        default=None, description="Zip / Postal code",
        json_schema_extra={"db_field": "postal_code"}
    )
    primary_phone: Optional[str] = Field(
        default=None, description="Primary phone number",
        json_schema_extra={"db_field": "primary_phone"}
    )
    secondary_phone: Optional[str] = Field(
        default=None, description="Secondary phone number",
        json_schema_extra={"db_field": "secondary_phone"}
    )
    fax: Optional[str] = Field(
        default=None, description="Fax number",
        json_schema_extra={"db_field": "fax"}
    )
    url: Optional[str] = Field(
        default=None, description="Website URL",
        json_schema_extra={"db_field": "url"}
    )
    state_code: Optional[str] = Field(
        default=None, description="State code",
        json_schema_extra={"db_field": "state_code"}
    )
    hs_type: Optional[str] = Field(
        default=None, description="School type",
        json_schema_extra={"db_field": "hs_type"}
    )
    hs_pay_type: Optional[str] = Field(
        default=None, description="Pay type (Student Pay / School Full Pay / School Partial Pay)",
        json_schema_extra={"db_field": "hs_pay_type"}
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

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in ('Active', 'Inactive'):
            raise ValueError("Must be 'Active' or 'Inactive'")
        return v

    @field_validator('hs_type')
    @classmethod
    def validate_hs_type(cls, v):
        """Normalise to tenant School Type codes.

        hs_type is multi-valued, so a cell may carry several types separated
        by ';'. Comma is unavailable: it is both the CSV delimiter and the
        separator MultiSelectField uses inside its single varchar column.

        Accepts either a code or a label (case-insensitive) so spreadsheets
        written before the code/label split keep importing.
        """
        if v is None:
            return v

        from cis.services.tenant_services import get_tenant_service
        types = get_tenant_service('highschool_types')

        codes, unknown = [], []
        for token in str(v).split(';'):
            if not token.strip():
                continue
            code = types.normalize(token)
            (codes if code else unknown).append(code or token.strip())

        if unknown:
            valid = ', '.join(types.labels(types.codes()))
            raise ValueError(
                f"Unknown School Type: {', '.join(unknown)}. Must be one of: {valid}"
            )
        return ';'.join(codes) if codes else None

    @field_validator('hs_pay_type')
    @classmethod
    def validate_hs_pay_type(cls, v):
        valid_values = [opt[0] for opt in HighSchool.PAY_TYPE_OPTIONS if opt[0]]
        if v is not None and v not in valid_values:
            raise ValueError(f"Must be one of: {', '.join(valid_values)}")
        return v

    @field_validator('sau', 'district_name', 'address1', 'address2', 'city', 'state',
                     'postal_code', 'primary_phone', 'secondary_phone', 'fax', 'url',
                     'state_code', 'hs_type', 'hs_pay_type', 'status', mode='before')
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
