"""
Pydantic schema for Term CSV import.

Single source of truth for:
- CSV column names and order
- Required vs optional fields
- Type validation and coercion
- Custom validation rules
"""
from pydantic import BaseModel, Field, field_validator


class TermRow(BaseModel):
    """Single source of truth for the Term CSV import schema."""

    # --- Required fields ---
    academic_year: str = Field(
        min_length=1, description="Academic year name (e.g. 2024-2025)",
        json_schema_extra={"db_field": "academic_year", "is_lookup": True}
    )
    name: str = Field(
        min_length=1, description="Term label (e.g. Fall, Spring)",
        json_schema_extra={"db_field": "label"}
    )
    code: str = Field(
        min_length=1, description="Term code",
        json_schema_extra={"db_field": "code"}
    )

    # --- Validators ---
    @field_validator('academic_year', mode='before')
    @classmethod
    def normalize_dash(cls, v):
        """Replace HTML entity dash with standard dash."""
        if isinstance(v, str):
            return v.replace('&#8211;', '-')
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
