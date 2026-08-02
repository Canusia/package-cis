"""
ClassSection CSV importer with bulk operations support.
"""
import logging
from typing import Dict, List, Optional, Tuple
from django.db import transaction
from django.db.models import Q
from pydantic import ValidationError as PydanticValidationError

from cis.models import ClassSection, Course, Cohort, AcademicYear
from .validation import ValidationError, ImportResult
from .class_section_schema import ClassSectionRow

logger = logging.getLogger(__name__)


class ClassSectionImporter:
    """Handles the complex logic of importing ClassSections from CSV"""

    def __init__(self, use_bulk_operations=True, batch_size=500, use_transactions='none'):
        """
        Initialize importer with options.

        Args:
            use_bulk_operations: If True, use bulk_create/bulk_update for better performance
            batch_size: Number of records to process in each bulk operation
            use_transactions: Transaction strategy:
                - 'none': No transactions (default - fastest, import all good rows)
                - 'per_batch': Transaction per batch
                - 'per_row': Transaction per row
                - 'all': Wrap entire import in transaction (all-or-nothing)
        """
        self.use_bulk_operations = use_bulk_operations
        self.batch_size = batch_size
        self.use_transactions = use_transactions

    def process_csv(self, dictReader) -> Dict:
        """
        Main entry point for CSV import.
        Transaction handling depends on use_transactions setting.
        """
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
        """Internal processing logic"""
        if self.use_bulk_operations:
            return self._process_csv_bulk(dictReader)
        else:
            return self._process_csv_individual(dictReader)

    def _process_csv_individual(self, dictReader) -> Dict:
        """
        Process CSV rows one at a time.
        Each row is independent - failures don't affect other rows.
        """
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
        """
        Process CSV using bulk operations for better performance.
        Bad rows are skipped, good rows are imported.
        """
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
                # No transaction - individual failures don't affect others
                batch_results = self._process_batch(batch)
                results.extend(batch_results)

        return self._build_summary(results)

    def _process_batch(self, batch: List[Tuple[int, Dict, ClassSectionRow]]) -> List[ImportResult]:
        """Process a batch of rows using bulk operations"""
        results = []

        # Phase 2a: Prepare all data
        prepared_data = []
        for index, row, validated in batch:
            try:
                related_objects = self._get_related_objects(validated)
                status = 'A' if (validated.cancel_flag or '').lower() == 'n' else 'C'

                prepared_data.append({
                    'index': index,
                    'row': row,
                    'validated': validated,
                    'related_objects': related_objects,
                    'status': status
                })
            except Exception as e:
                logger.error(f"Failed to prepare row {index}: {e}", exc_info=True)
                row['RESULT'] = str(e)
                results.append(ImportResult(success=False, row_data=row, error_message=str(e)))

        if not prepared_data:
            return results

        # Phase 2b: Fetch existing records in bulk
        term_class_pairs = [
            (d['related_objects']['term'].id, d['validated'].reference_number)
            for d in prepared_data
        ]

        existing_records = self._fetch_existing_records(term_class_pairs)

        # Phase 2c: Separate creates from updates
        to_create = []
        to_update = []

        for data in prepared_data:
            term_id = data['related_objects']['term'].id
            class_number = data['validated'].reference_number
            key = (term_id, class_number)

            if key in existing_records:
                class_section = existing_records[key]
                self._update_class_section(class_section, data)
                to_update.append(class_section)
            else:
                class_section = self._create_class_section_instance(data)
                to_create.append(class_section)

        # Phase 2d: Execute bulk operations
        created_count = 0
        updated_count = 0

        if to_create:
            try:
                ClassSection.objects.bulk_create(to_create, batch_size=100)
                created_count = len(to_create)
                logger.info(f"Bulk created {created_count} records")
            except Exception as e:
                logger.error(f"Bulk create failed: {e}", exc_info=True)

                if self.use_transactions == 'per_batch':
                    raise
                else:
                    # Try individual saves as fallback
                    for cs in to_create:
                        try:
                            cs.save()
                            created_count += 1
                        except Exception as save_error:
                            # Per-row failures during a bulk import are
                            # expected; log at WARNING so they don't trigger
                            # the AdminEmailHandler.
                            logger.warning(f"Failed to save {cs.class_number}: {save_error}")

        if to_update:
            try:
                # Use UPDATABLE_FIELDS from the model for bulk_update
                ClassSection.objects.bulk_update(
                    to_update,
                    fields=ClassSection.UPDATABLE_FIELDS,
                    batch_size=100
                )
                updated_count = len(to_update)
                logger.info(f"Bulk updated {updated_count} records")
            except Exception as e:
                logger.error(f"Bulk update failed: {e}", exc_info=True)

                if self.use_transactions == 'per_batch':
                    raise
                else:
                    # Try individual updates as fallback
                    for cs in to_update:
                        try:
                            cs.save()
                            updated_count += 1
                        except Exception as save_error:
                            # Per-row failures during a bulk import are
                            # expected; log at WARNING so they don't trigger
                            # the AdminEmailHandler.
                            logger.warning(f"Failed to update {cs.class_number}: {save_error}")

        # Phase 2e: Build results
        for data in prepared_data:
            data['row']['RESULT'] = 'Success'
            results.append(ImportResult(success=True, row_data=data['row']))

        logger.info(f"Batch complete: {created_count} created, {updated_count} updated")

        return results

    def _fetch_existing_records(self, term_class_pairs: List[Tuple]) -> Dict:
        """Fetch existing ClassSection records in bulk"""
        if not term_class_pairs:
            return {}

        query = Q()
        for term_id, class_number in term_class_pairs:
            query |= Q(term_id=term_id, class_number=class_number)

        existing = ClassSection.objects.filter(query).select_related(
            'term', 'course', 'teacher', 'highschool', 'campus', 'location', 'registration_term'
        )

        return {
            (cs.term_id, cs.class_number): cs
            for cs in existing
        }

    def _build_db_fields(self, data: Dict) -> Dict:
        """
        Build model field dict from validated schema data and related objects.
        Uses ClassSectionRow.db_field_mapping() for direct fields and
        overlays FK lookups from related_objects.
        """
        validated = data['validated']
        related = data['related_objects']

        # Direct fields from schema mapping
        field_mapping = {}
        for csv_col, db_field in ClassSectionRow.db_field_mapping().items():
            value = getattr(validated, csv_col)
            if value is not None:
                field_mapping[db_field] = value

        # FK lookup fields
        field_mapping['term'] = related['term']
        field_mapping['course'] = related['course']
        field_mapping['teacher'] = related.get('teacher')
        field_mapping['highschool'] = related.get('highschool')
        field_mapping['registration_term'] = related['registration_term']

        # Derived fields
        field_mapping['status'] = data['status']

        return field_mapping

    def _create_class_section_instance(self, data: Dict) -> ClassSection:
        """
        Create a new ClassSection instance.
        Uses schema db_field_mapping for field resolution.
        """
        field_mapping = self._build_db_fields(data)
        return ClassSection(**field_mapping)

    def _update_class_section(self, class_section: ClassSection, data: Dict):
        """
        Update an existing ClassSection instance.
        Only updates fields that are in UPDATABLE_FIELDS.
        """
        field_mapping = self._build_db_fields(data)

        for field_name, value in field_mapping.items():
            if field_name in ClassSection.UPDATABLE_FIELDS:
                setattr(class_section, field_name, value)

    def _build_summary(self, results: List[ImportResult]) -> Dict:
        """Build final summary"""
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
        """
        Process a single row (used in non-bulk mode).
        Uses the same create/update methods as bulk mode for consistency.
        """
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
            status = 'A' if (validated.cancel_flag or '').lower() == 'n' else 'C'

            # Prepare data structure (same as bulk mode)
            data = {
                'validated': validated,
                'related_objects': related_objects,
                'status': status
            }

            # Check if record exists and update or create
            try:
                class_section = ClassSection.objects.get(
                    term=related_objects['term'],
                    class_number=validated.reference_number
                )
                self._update_class_section(class_section, data)
                class_section.save()
            except ClassSection.DoesNotExist:
                class_section = self._create_class_section_instance(data)
                class_section.save()

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

    def _validate_and_clean_row(self, row: Dict) -> Tuple[Optional[ClassSectionRow], List[ValidationError]]:
        """
        Validate and clean a CSV row using the pydantic schema.
        Returns (validated_row, errors) - if errors is non-empty, validated_row is None.
        """
        try:
            validated = ClassSectionRow.model_validate(row)
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

    def _get_related_objects(self, validated: ClassSectionRow) -> Dict:
        """Lookup or create all related objects from validated schema data"""
        related = {}

        related['course'] = self._get_or_create_course(
            validated.course_name,
            validated.course_title,
            validated.credit_hours or 0
        )

        related['teacher'] = self._get_teacher(validated.teacher_hs_email)
        related['highschool'] = self._get_highschool(validated.highschool_ceeb)

        related['term'] = self._get_term(validated.term_code)
        if not related['term']:
            raise ValueError(f"Term does not exist: {validated.term_code}")

        related['registration_term'] = self._get_or_create_registration_term(
            validated.registration_term_code
        )

        return related

    def _get_or_create_course(self, course_name: str, course_title: str, credits: float):
        """Get or create a course"""
        try:
            return Course.objects.get(name=course_name)
        except Course.DoesNotExist:
            cohort_name, catalog = course_name.split(' ', 1)
            cohort, _ = Cohort.objects.get_or_create(
                name=cohort_name,
                designator=cohort_name
            )
            course, _ = Course.objects.get_or_create(
                cohort=cohort,
                name=course_name,
                defaults={
                    'title': course_title,
                    'credit_hours': credits
                }
            )
            return course

    def _get_teacher(self, teacher_email: Optional[str]):
        """Get teacher by email"""
        from cis.models.teacher import Teacher

        if not teacher_email:
            return None

        try:
            return Teacher.objects.get(user__secondary_email=teacher_email)
        except Teacher.DoesNotExist:
            logger.warning(f"Teacher not found with email: {teacher_email}")
            return None

    def _get_highschool(self, ceeb_code: Optional[str]):
        """Get highschool by CEEB code"""
        from cis.models.highschool import HighSchool

        if not ceeb_code:
            return None

        try:
            return HighSchool.objects.get(code=ceeb_code)
        except HighSchool.DoesNotExist:
            logger.warning(f"HighSchool not found with code: {ceeb_code}")
            return None

    def _get_term(self, term_code: str):
        """Get term by code"""
        from cis.models.term import Term
        return Term.objects.filter(code=term_code).first()

    def _get_or_create_registration_term(self, term_code: str):
        """Get or create registration term"""
        from cis.models.term import Term

        if not Term.objects.filter(code=term_code).exists():
            registration_term, _ = Term.objects.get_or_create(
                code=term_code,
                defaults={
                    'label': f"{term_code}",
                    'academic_year': AcademicYear.objects.first()
                }
            )
            return registration_term

        return Term.objects.filter(code=term_code).first()
