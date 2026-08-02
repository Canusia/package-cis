"""
Course CSV importer — individual row processing only.

Mirrors the logic from the ``import_course`` management command but adds
pydantic validation and structured result reporting.
"""
import logging
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError as PydanticValidationError

from cis.models.course import Cohort, Course
from .validation import ValidationError, ImportResult
from .course_schema import CourseRow

logger = logging.getLogger(__name__)


class CourseImporter:
    """Handles importing Courses from CSV."""

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

            # 1. Split course name into subject + catalog_number
            parts = validated.name.split(' ', 1)
            if len(parts) == 2:
                _, cat_num = parts
            else:
                cat_num = parts[0]

            # 2. Get or create cohort from subject designator
            cohort, _ = Cohort.objects.get_or_create(
                designator=validated.subject,
                defaults={'name': validated.subject},
            )

            # 3. Add or update the course
            course = Course.add_or_update(
                name=validated.name,
                catalog_number=cat_num,
                cohort=cohort,
                title=validated.title,
                credit_hours=validated.credits,
                status=validated.status,
                description=validated.course_description or '',
                prereq=validated.prereq or '',
                teacher_requirement=validated.teacher_reqs or '',
            )

            row['RESULT'] = 'Success'
            return ImportResult(success=True, row_data=row)

        except Exception as e:
            logger.error("Failed to import row %d: %s", index, str(e), exc_info=True)
            row['RESULT'] = str(e)
            return ImportResult(success=False, row_data=row, error_message=str(e))

    def _validate_and_clean_row(
        self, row: Dict
    ) -> Tuple[Optional[CourseRow], List[ValidationError]]:
        """Validate and clean a CSV row using the pydantic schema."""
        try:
            validated = CourseRow.model_validate(row)
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
