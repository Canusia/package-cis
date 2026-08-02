"""
Pydantic schema for Cohort (Subject) CSV import.

Single source of truth for:
- CSV column names and order
- Required vs optional fields
- Type validation and coercion
- Custom validation rules
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional


class CohortRow(BaseModel):
    """Single source of truth for the Cohort CSV import schema."""

    # --- Required fields ---
    designator: str = Field(
        min_length=1, description="Subject designator (e.g. ENG)",
        json_schema_extra={"db_field": "designator"}
    )
    name: str = Field(
        min_length=1, description="Subject/program name",
        json_schema_extra={"db_field": "name"}
    )

    # --- Optional fields ---
    status: Optional[str] = Field(
        default="Active", description="Status (Active / Inactive)",
        json_schema_extra={"db_field": "status"}
    )

    # --- Validators ---
    @field_validator('status', mode='before')
    @classmethod
    def validate_status(cls, v):
        if v is None or v == '':
            return 'Active'
        if v not in ('Active', 'Inactive'):
            raise ValueError("Must be 'Active' or 'Inactive'")
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
