"""
HighSchool CSV importer with bulk operations support.
"""
import logging
from typing import Dict, List, Optional, Tuple
from django.db import transaction
from pydantic import ValidationError as PydanticValidationError

from cis.models.highschool import HighSchool
from cis.models.district import District
from .validation import ValidationError, ImportResult
from .highschool_schema import HighSchoolRow

logger = logging.getLogger(__name__)


class HighSchoolImporter:
    """Handles importing HighSchools from CSV"""

    def __init__(self, use_bulk_operations=True, batch_size=500, use_transactions='none'):
        self.use_bulk_operations = use_bulk_operations
        self.batch_size = batch_size
        self.use_transactions = use_transactions

    def process_csv(self, dictReader) -> Dict:
        """Main entry point for CSV import."""
        try:
            if self.use_transactions == 'all':
                with transaction.atomic():
                    return self._process_csv_internal(dictReader)
            else:
                return self._process_csv_internal(dictReader)
        except Exception as e:
            logger.error(f"CSV import failed: {e}", exc_info=True)
            raise

    def _process_csv_internal(self, dictReader) -> Dict:
        if self.use_bulk_operations:
            return self._process_csv_bulk(dictReader)
        else:
            return self._process_csv_individual(dictReader)

    def _process_csv_individual(self, dictReader) -> Dict:
        results = []
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
                'failed': failed_imports
            }
        }

    def _process_csv_bulk(self, dictReader) -> Dict:
        results = []
        valid_rows = []

        # Phase 1: Validate all rows using pydantic schema
        logger.info("Phase 1: Validating rows...")
        for index, row in enumerate(dictReader, start=1):
            validated, validation_errors = self._validate_and_clean_row(row)

            if validation_errors:
                error_messages = [f"{e.field}: {e.message}" for e in validation_errors]
                full_error = f"Validation failed - {'; '.join(error_messages)}"
                row['RESULT'] = full_error
                results.append(ImportResult(
                    success=False,
                    row_data=row,
                    error_message=full_error,
                    validation_errors=validation_errors
                ))
            else:
                valid_rows.append((index, row, validated))

        if not valid_rows:
            logger.warning("No valid rows to import")
            return self._build_summary(results)

        logger.info(f"Phase 1 complete: {len(valid_rows)} valid rows, {len(results)} invalid rows")

        # Phase 2: Process valid rows in batches
        logger.info("Phase 2: Processing valid rows in batches...")

        for batch_start in range(0, len(valid_rows), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(valid_rows))
            batch = valid_rows[batch_start:batch_end]

            logger.info(f"Processing batch {batch_start}-{batch_end} of {len(valid_rows)}")

            if self.use_transactions == 'per_batch':
                try:
                    with transaction.atomic():
                        batch_results = self._process_batch(batch)
                        results.extend(batch_results)
                except Exception as e:
                    logger.error(f"Batch {batch_start}-{batch_end} failed: {e}", exc_info=True)
                    for index, row, validated in batch:
                        row['RESULT'] = f"Batch failed: {str(e)}"
                        results.append(ImportResult(
                            success=False,
                            row_data=row,
                            error_message=str(e)
                        ))
            else:
                batch_results = self._process_batch(batch)
                results.extend(batch_results)

        return self._build_summary(results)

    def _process_batch(self, batch: List[Tuple[int, Dict, HighSchoolRow]]) -> List[ImportResult]:
        """Process a batch of rows using bulk operations."""
        results = []

        # Phase 2a: Prepare all data (resolve FK lookups)
        prepared_data = []
        for index, row, validated in batch:
            try:
                related_objects = self._get_related_objects(validated)
                prepared_data.append({
                    'index': index,
                    'row': row,
                    'validated': validated,
                    'related_objects': related_objects,
                })
            except Exception as e:
                logger.error(f"Failed to prepare row {index}: {e}", exc_info=True)
                row['RESULT'] = str(e)
                results.append(ImportResult(success=False, row_data=row, error_message=str(e)))

        if not prepared_data:
            return results

        # Phase 2b: Fetch existing records in bulk (match by code)
        codes = [d['validated'].code for d in prepared_data]
        existing_records = self._fetch_existing_records(codes)

        # Phase 2c: Separate creates from updates
        to_create = []
        to_update = []

        for data in prepared_data:
            key = data['validated'].code

            if key in existing_records:
                highschool = existing_records[key]
                self._update_highschool(highschool, data)
                to_update.append(highschool)
            else:
                highschool = self._create_highschool_instance(data)
                to_create.append(highschool)

        # Phase 2d: Execute bulk operations
        created_count = 0
        updated_count = 0

        if to_create:
            try:
                HighSchool.objects.bulk_create(to_create, batch_size=100)
                created_count = len(to_create)
                logger.info(f"Bulk created {created_count} records")
            except Exception as e:
                logger.error(f"Bulk create failed: {e}", exc_info=True)
                if self.use_transactions == 'per_batch':
                    raise
                else:
                    for hs in to_create:
                        try:
                            hs.save()
                            created_count += 1
                        except Exception as save_error:
                            logger.error(f"Failed to save {hs.name}: {save_error}")

        if to_update:
            update_fields = [
                'name', 'sau', 'status', 'district', 'address1', 'address2',
                'city', 'state', 'postal_code', 'primary_phone', 'secondary_phone',
                'fax', 'url', 'state_code', 'hs_type', 'hs_pay_type',
            ]
            try:
                HighSchool.objects.bulk_update(to_update, fields=update_fields, batch_size=100)
                updated_count = len(to_update)
                logger.info(f"Bulk updated {updated_count} records")
            except Exception as e:
                logger.error(f"Bulk update failed: {e}", exc_info=True)
                if self.use_transactions == 'per_batch':
                    raise
                else:
                    for hs in to_update:
                        try:
                            hs.save()
                            updated_count += 1
                        except Exception as save_error:
                            logger.error(f"Failed to update {hs.name}: {save_error}")

        # Phase 2e: Build results
        for data in prepared_data:
            data['row']['RESULT'] = 'Success'
            results.append(ImportResult(success=True, row_data=data['row']))

        logger.info(f"Batch complete: {created_count} created, {updated_count} updated")
        return results

    def _fetch_existing_records(self, codes: List[str]) -> Dict:
        """Fetch existing HighSchool records in bulk, keyed by code."""
        if not codes:
            return {}
        existing = HighSchool.objects.filter(code__in=codes).select_related('district')
        return {hs.code: hs for hs in existing}

    def _build_db_fields(self, data: Dict) -> Dict:
        """Build model field dict from validated schema data and related objects."""
        validated = data['validated']
        related = data['related_objects']

        field_mapping = {}
        for csv_col, db_field in HighSchoolRow.db_field_mapping().items():
            value = getattr(validated, csv_col)
            if value is not None:
                field_mapping[db_field] = value

        # hs_type is a MultiSelectField and needs a list, not a string. The
        # schema validator normalises the cell to ';'-joined tenant codes.
        if field_mapping.get('hs_type'):
            field_mapping['hs_type'] = field_mapping['hs_type'].split(';')

        # FK lookup fields
        field_mapping['district'] = related.get('district')

        return field_mapping

    def _create_highschool_instance(self, data: Dict) -> HighSchool:
        field_mapping = self._build_db_fields(data)
        return HighSchool(**field_mapping)

    def _update_highschool(self, highschool: HighSchool, data: Dict):
        field_mapping = self._build_db_fields(data)
        for field_name, value in field_mapping.items():
            if field_name != 'code':  # Don't update the match key
                setattr(highschool, field_name, value)

    def _build_summary(self, results: List[ImportResult]) -> Dict:
        successful = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)

        return {
            'status': 'success',
            'records': [r.row_data for r in results],
            'summary': {
                'total': len(results),
                'successful': successful,
                'failed': failed
            }
        }

    def _process_row(self, row: Dict, index: int) -> ImportResult:
        """Process a single row (used in non-bulk mode)."""
        def process():
            validated, validation_errors = self._validate_and_clean_row(row)

            if validation_errors:
                error_messages = [f"{e.field}: {e.message}" for e in validation_errors]
                full_error = f"Validation failed - {'; '.join(error_messages)}"
                logger.warning(f"Row {index} validation failed: {full_error}")
                row['RESULT'] = full_error
                return ImportResult(
                    success=False,
                    row_data=row,
                    error_message=full_error,
                    validation_errors=validation_errors
                )

            related_objects = self._get_related_objects(validated)

            data = {
                'validated': validated,
                'related_objects': related_objects,
            }

            # Check if record exists by code and update or create
            try:
                highschool = HighSchool.objects.get(code=validated.code)
                self._update_highschool(highschool, data)
                highschool.save()
            except HighSchool.DoesNotExist:
                highschool = self._create_highschool_instance(data)
                highschool.save()

            row['RESULT'] = 'Success'
            return ImportResult(success=True, row_data=row)

        try:
            if self.use_transactions == 'per_row':
                with transaction.atomic():
                    return process()
            else:
                return process()
        except Exception as e:
            logger.error(f"Failed to import row {index}: {str(e)}", exc_info=True)
            row['RESULT'] = str(e)
            return ImportResult(success=False, row_data=row, error_message=str(e))

    def _validate_and_clean_row(self, row: Dict) -> Tuple[Optional[HighSchoolRow], List[ValidationError]]:
        """Validate and clean a CSV row using the pydantic schema."""
        try:
            validated = HighSchoolRow.model_validate(row)
            return validated, []
        except PydanticValidationError as e:
            errors = []
            for err in e.errors():
                field_name = err['loc'][0] if err['loc'] else 'unknown'
                errors.append(ValidationError(
                    field=str(field_name),
                    message=err['msg']
                ))
            return None, errors

    def _get_related_objects(self, validated: HighSchoolRow) -> Dict:
        """Lookup or create all related objects from validated schema data."""
        related = {}

        if validated.district_name:
            related['district'] = District.get_or_add(validated.district_name)
        else:
            related['district'] = None

        return related
