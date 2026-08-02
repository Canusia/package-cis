"""
Instructor (Teacher) CSV importer — individual row processing.

Each row creates/reuses a Teacher (+ CustomUser), links it to a high school by
CEEB code (TeacherHighSchool), and creates a TeacherCourseCertificate for each
listed course. Matching is by psid, else primary email; existing teachers are
reused without field updates (links are still ensured). Mirrors HSMemberImporter.
"""
import logging
from typing import Dict, List, Optional, Tuple

from django.contrib.auth.models import Group
from django.db import transaction
from pydantic import ValidationError as PydanticValidationError

from cis.models.customuser import CustomUser
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.highschool import HighSchool
from cis.models.course import Course
from .validation import ValidationError, ImportResult
from .instructor_schema import InstructorRow

logger = logging.getLogger(__name__)


class InstructorImporter:
    """Handles importing Instructors (Teachers) from CSV."""

    def process_csv(self, dictReader) -> Dict:
        """Main entry point for CSV import."""
        results: List[ImportResult] = []
        successful = 0
        failed = 0

        for index, row in enumerate(dictReader, start=1):
            result = self._process_row(row, index)
            results.append(result)
            if result.success:
                successful += 1
            else:
                failed += 1

        return {
            'status': 'success',
            'records': [r.row_data for r in results],
            'summary': {
                'total': len(results),
                'successful': successful,
                'failed': failed,
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
                msgs = [f"{e.field}: {e.message}" for e in validation_errors]
                full = f"Validation failed - {'; '.join(msgs)}"
                logger.warning("Row %d validation failed: %s", index, full)
                row['RESULT'] = full
                return ImportResult(
                    success=False,
                    row_data=row,
                    error_message=full,
                    validation_errors=validation_errors,
                )

            with transaction.atomic():
                highschool = HighSchool.objects.get(code=validated.highschool_ceeb)

                teacher = self._find_teacher(validated)
                if teacher is None:
                    teacher = self._create_teacher(validated)

                ths, _ = TeacherHighSchool.objects.get_or_create(
                    teacher=teacher, highschool=highschool)

                notes = self._ensure_certificates(ths, validated)

            row['RESULT'] = 'Success' if not notes else 'Success - ' + '; '.join(notes)
            return ImportResult(success=True, row_data=row)

        except HighSchool.DoesNotExist:
            msg = f"High school with CEEB code '{row.get('highschool_ceeb', '')}' not found"
            logger.error("Row %d: %s", index, msg)
            row['RESULT'] = msg
            return ImportResult(success=False, row_data=row, error_message=msg)
        except Exception as e:
            logger.error("Failed to import row %d: %s", index, str(e), exc_info=True)
            row['RESULT'] = str(e)
            return ImportResult(success=False, row_data=row, error_message=str(e))

    def _find_teacher(self, v: InstructorRow) -> Optional[Teacher]:
        """Look up an existing Teacher by psid, falling back to primary email."""
        teacher = None
        if v.teacherid:
            teacher = Teacher.objects.filter(user__psid=v.teacherid).first()
        if teacher is None and v.primary_email:
            teacher = Teacher.objects.filter(
                user__email__iexact=v.primary_email).first()
        return teacher

    def _create_teacher(self, v: InstructorRow) -> Teacher:
        """Create a new CustomUser + Teacher and add to the instructor group."""
        user = CustomUser(
            username=v.teacher_id.lower(),
            email=v.primary_email,
            psid=v.teacherid,
            alt_username=v.teacher_id,
            first_name=v.first_name,
            last_name=v.last_name,
            middle_name=v.middle_name or '',
            secondary_email=v.secondary_email or '',
            alt_email=v.home_email or '',
            address1=v.home_address or '',
            city=v.home_city or '',
            state=v.home_state or '',
            postal_code=v.home_zip or '',
            primary_phone=v.cell_phone or '',
            secondary_phone=v.home_phone or '',
            date_of_birth=v.date_of_birth,
        )
        user.save()

        teacher = Teacher(user=user, status=v.status, orientation_date=v.orientation_date)
        teacher.save()
        teacher.user.groups.add(Group.objects.get(name='instructor'))
        return teacher

    def _ensure_certificates(self, ths: TeacherHighSchool, v: InstructorRow) -> List[str]:
        """Create get_or_create TeacherCourseCertificate for each non-empty course column."""
        notes: List[str] = []
        for col in InstructorRow.course_columns():
            name = getattr(v, col)
            if not name:
                continue
            course = Course.objects.filter(name=name).first()
            if course is None:
                notes.append(f"course not found: {name}")
                continue
            TeacherCourseCertificate.objects.get_or_create(
                teacher_highschool=ths,
                course=course,
                defaults={'since': v.date_of_hire},
            )
        return notes

    def _validate_and_clean_row(
        self, row: Dict
    ) -> Tuple[Optional[InstructorRow], List[ValidationError]]:
        """Validate and clean a CSV row using the pydantic schema."""
        try:
            return InstructorRow.model_validate(row), []
        except PydanticValidationError as e:
            errors = []
            for err in e.errors():
                field_name = err['loc'][0] if err['loc'] else 'unknown'
                errors.append(ValidationError(
                    field=str(field_name),
                    message=err['msg'],
                ))
            return None, errors
