"""
Faculty CSV importer — per-row processing.

Each row creates/reuses a CustomUser (deduped by email) + a FacultyCoordinator
(whose save() adds the 'faculty' group), then assigns the faculty as a
CourseAdministrator (role Faculty/Visitor) for each course/role pair.
Mirrors InstructorImporter.
"""
import logging
from typing import Dict, List, Optional, Tuple

from django.db import transaction
from pydantic import ValidationError as PydanticValidationError

from cis.models.customuser import CustomUser
from cis.models.faculty import FacultyCoordinator
from cis.models.course import Course, CourseAdministrator
from .validation import ValidationError, ImportResult
from .faculty_schema import FacultyRow

logger = logging.getLogger(__name__)


class FacultyImporter:
    """Handles importing Faculty from CSV."""

    def process_csv(self, dictReader) -> Dict:
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
            'summary': {'total': len(results), 'successful': successful, 'failed': failed},
        }

    def _process_row(self, row: Dict, index: int) -> ImportResult:
        try:
            validated, validation_errors = self._validate_and_clean_row(row)
            if validation_errors:
                msgs = [f"{e.field}: {e.message}" for e in validation_errors]
                full = f"Validation failed - {'; '.join(msgs)}"
                logger.warning("Row %d validation failed: %s", index, full)
                row['RESULT'] = full
                return ImportResult(success=False, row_data=row,
                                    error_message=full, validation_errors=validation_errors)

            with transaction.atomic():
                user, user_existed = self._find_or_create_user(validated)
                faculty_existed = FacultyCoordinator.objects.filter(user=user).exists()
                notes: List[str] = []
                if user_existed and not faculty_existed:
                    notes.append(f"added faculty role to existing account {user.email}")
                self._ensure_faculty(user, validated)
                self._assign_courses(user, validated, notes)

            row['RESULT'] = 'Success' if not notes else 'Success - ' + '; '.join(notes)
            return ImportResult(success=True, row_data=row)
        except Exception as e:
            logger.error("Failed to import faculty row %d: %s", index, str(e), exc_info=True)
            row['RESULT'] = str(e)
            return ImportResult(success=False, row_data=row, error_message=str(e))

    def _find_or_create_user(self, v: FacultyRow) -> Tuple[CustomUser, bool]:
        """Dedup by case-insensitive email match; create with username=email.lower() if absent.

        Returns (user, user_existed) so the caller can note when an existing
        account is being promoted to faculty.
        """
        existing = CustomUser.objects.filter(email__iexact=v.email).first()
        if existing:
            return existing, True
        user = CustomUser(
            username=v.email.lower(),
            email=v.email,
            psid=v.psid or '',
            first_name=v.first_name,
            last_name=v.last_name,
            middle_name=v.middle_name or '',
            secondary_email=v.secondary_email or '',
            primary_phone=v.primary_phone or '',
            address1=v.address1 or '',
            city=v.city or '',
            state=v.state or '',
            postal_code=v.postal_code or '',
        )
        user.save()
        return user, False

    def _ensure_faculty(self, user: CustomUser, v: FacultyRow) -> FacultyCoordinator:
        """Create the FacultyCoordinator if absent (its save() adds the 'faculty' group)."""
        faculty = FacultyCoordinator.objects.filter(user=user).first()
        if faculty is None:
            faculty = FacultyCoordinator(user=user, status=v.status)
            faculty.save()  # save() override adds the 'faculty' group
        return faculty

    def _assign_courses(self, user: CustomUser, v: FacultyRow, notes: List[str]) -> List[str]:
        """For each course/role pair, look up the Active course by name and assign.

        Appends any per-pair diagnostics to ``notes`` (shared with the row-level
        notes) and returns it.
        """
        for course_col, role_col in FacultyRow.course_role_pairs():
            name = getattr(v, course_col)
            role = getattr(v, role_col)
            if not name and role:
                notes.append(f"role '{role}' given but course is blank")
                continue
            if not name:
                continue
            if not role:
                notes.append(f"missing role for course '{name}'")
                continue
            if role not in ('Faculty', 'Visitor'):
                notes.append(f"invalid role '{role}' for course '{name}'")
                continue
            matches = list(
                Course.objects.filter(name__iexact=name, status__iexact='Active')[:2])
            if not matches:
                notes.append(f"course not found (active): '{name}'")
                continue
            if len(matches) > 1:
                notes.append(f"ambiguous course name: '{name}'")
                continue
            course = matches[0]
            existing = CourseAdministrator.objects.filter(
                course=course, user=user, role=role).first()
            if existing is None:
                CourseAdministrator.objects.create(
                    course=course, user=user, role=role)
        return notes

    def _validate_and_clean_row(
        self, row: Dict
    ) -> Tuple[Optional[FacultyRow], List[ValidationError]]:
        try:
            return FacultyRow.model_validate(row), []
        except PydanticValidationError as e:
            errors = []
            for err in e.errors():
                field_name = err['loc'][0] if err['loc'] else 'unknown'
                errors.append(ValidationError(field=str(field_name), message=err['msg']))
            return None, errors
