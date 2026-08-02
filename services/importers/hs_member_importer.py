"""
HS Member (HSAdministrator) CSV importer — individual row processing only.

Each row can create multiple position records (one per CEEB code), so bulk
operations are not practical.  Processing mirrors the legacy
``import_hs_members`` management command but adds pydantic validation and
structured result reporting.
"""
import logging
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError as PydanticValidationError

from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSPosition, HSAdministratorPosition,
)
from .validation import ValidationError, ImportResult
from .hs_member_schema import HSMemberRow

logger = logging.getLogger(__name__)


class HSMemberImporter:
    """Handles importing HS Members (HSAdministrators) from CSV."""

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

            # 1. Create or find the HSAdministrator via CustomUser
            hs_member = HSAdministrator.get_or_add(
                email=validated.email,
                first_name=validated.firstname,
                last_name=validated.lastname,
                primary_phone=validated.phone or '',
                fax=validated.fax or '',
                middle_name=validated.middlename or '',
                salutation=validated.salutation or '',
            )

            if hs_member is None:
                row['RESULT'] = 'Failed to create HS Administrator record'
                return ImportResult(
                    success=False,
                    row_data=row,
                    error_message='Failed to create HS Administrator record',
                )

            # 2. Process each CEEB code → position link
            ceebs = validated.ceeb.split(',')
            for ceeb in ceebs:
                ceeb = ceeb.strip()
                if not ceeb:
                    continue

                highschool = HighSchool.objects.get(code=ceeb)
                hs_position = HSPosition.get_or_add(name=validated.position_title)
                HSAdministratorPosition.get_or_add(
                    hsadmin=hs_member,
                    highschool=highschool,
                    position=hs_position,
                    status=validated.status,
                )

            row['RESULT'] = 'Success'
            return ImportResult(success=True, row_data=row)

        except HighSchool.DoesNotExist:
            msg = f"High school with CEEB code not found"
            logger.error("Row %d: %s", index, msg)
            row['RESULT'] = msg
            return ImportResult(success=False, row_data=row, error_message=msg)
        except Exception as e:
            logger.error("Failed to import row %d: %s", index, str(e), exc_info=True)
            row['RESULT'] = str(e)
            return ImportResult(success=False, row_data=row, error_message=str(e))

    def _validate_and_clean_row(
        self, row: Dict
    ) -> Tuple[Optional[HSMemberRow], List[ValidationError]]:
        """Validate and clean a CSV row using the pydantic schema."""
        try:
            validated = HSMemberRow.model_validate(row)
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
