"""
Cohort (Subject) CSV importer — individual row processing only.
"""
import logging
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError as PydanticValidationError

from cis.models.course import Cohort
from .validation import ValidationError, ImportResult
from .cohort_schema import CohortRow

logger = logging.getLogger(__name__)


class CohortImporter:
    """Handles importing Cohorts (Subjects) from CSV."""

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

            cohort = Cohort.get_or_add(
                cohort_designator=validated.designator,
                title=validated.name,
            )

            # Update status if provided
            if validated.status:
                cohort.status = validated.status
                cohort.save()

            row['RESULT'] = 'Success'
            return ImportResult(success=True, row_data=row)

        except Exception as e:
            logger.error("Failed to import row %d: %s", index, str(e), exc_info=True)
            row['RESULT'] = str(e)
            return ImportResult(success=False, row_data=row, error_message=str(e))

    def _validate_and_clean_row(
        self, row: Dict
    ) -> Tuple[Optional[CohortRow], List[ValidationError]]:
        """Validate and clean a CSV row using the pydantic schema."""
        try:
            validated = CohortRow.model_validate(row)
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
