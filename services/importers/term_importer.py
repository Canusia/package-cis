"""
Term CSV importer — individual row processing only.
"""
import logging
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError as PydanticValidationError

from cis.models.term import AcademicYear, Term
from .validation import ValidationError, ImportResult
from .term_schema import TermRow

logger = logging.getLogger(__name__)


class TermImporter:
    """Handles importing Terms from CSV."""

    def process_csv(self, dictReader) -> Dict:
        """Main entry point for CSV import."""
        results: List[ImportResult] = []
        successful_imports = 0
        failed_imports = 0

        for index, row in enumerate(dictReader, start=1):
            result = self._process_row(row, index)
            results.append(result)

            if result.success:
                successful_imports += 1
            else:
                failed_imports += 1

        return {
            'status': 'success',
            'records': [r.row_data for r in results],
            'summary': {
                'total': len(results),
                'successful': successful_imports,
                'failed': failed_imports,
            },
        }

    def _process_row(self, row: Dict, index: int) -> ImportResult:
        """Validate and import a single CSV row."""
        try:
            validated, validation_errors = self._validate_and_clean_row(row)

            if validation_errors:
                error_messages = [f"{e.field}: {e.message}" for e in validation_errors]
                full_error = f"Validation failed - {'; '.join(error_messages)}"
                logger.warning("Row %d validation failed: %s", index, full_error)
                row['RESULT'] = full_error
                return ImportResult(
                    success=False,
                    row_data=row,
                    error_message=full_error,
                    validation_errors=validation_errors,
                )

            # 1. Get or create the academic year
            academic_year = AcademicYear.get_or_add(name=validated.academic_year)

            if academic_year is None or isinstance(academic_year, type(AcademicYear.objects.none())):
                row['RESULT'] = 'Failed to create Academic Year record'
                return ImportResult(
                    success=False,
                    row_data=row,
                    error_message='Failed to create Academic Year record',
                )

            # 2. Get or create the term
            term = Term.get_or_add(
                academic_year=academic_year,
                label=validated.name,
                code=validated.code,
            )

            if term is None or isinstance(term, type(Term.objects.none())):
                row['RESULT'] = 'Failed to create Term record'
                return ImportResult(
                    success=False,
                    row_data=row,
                    error_message='Failed to create Term record',
                )

            row['RESULT'] = 'Success'
            return ImportResult(success=True, row_data=row)

        except Exception as e:
            logger.error("Failed to import row %d: %s", index, str(e), exc_info=True)
            row['RESULT'] = str(e)
            return ImportResult(success=False, row_data=row, error_message=str(e))

    def _validate_and_clean_row(
        self, row: Dict
    ) -> Tuple[Optional[TermRow], List[ValidationError]]:
        """Validate and clean a CSV row using the pydantic schema."""
        try:
            validated = TermRow.model_validate(row)
            return validated, []
        except PydanticValidationError as e:
            errors = []
            for err in e.errors():
                field_name = err['loc'][0] if err['loc'] else 'unknown'
                errors.append(ValidationError(
                    field=str(field_name),
                    message=err['msg'],
                ))
            return None, errors
