"""
Shared validation and result classes for importers.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ValidationError:
    """Represents a validation error for a specific field"""
    field: str
    message: str


@dataclass
class ImportResult:
    """Structured result for each row import"""
    success: bool
    row_data: Dict
    error_message: Optional[str] = None
    validation_errors: List[ValidationError] = field(default_factory=list)