"""Regression tests for the needs-mirroring-on-create bug.

`update_registration` (post_save on StudentRegistration,
cis/signals/registrations.py) used to only consult the sis_mirror_trigger
setting inside the `previous_status != status` guard, which FieldTracker
never satisfies on creation. A registration created DIRECTLY at a trigger
status was therefore never queued for the SIS mirror, while one created at
another status and later moved into a trigger status was queued correctly.

These tests pin down the fixed behaviour: creation now consults the same
setting the status-change path does, and existing status-change behaviour
(including the coreq propagation path) is unchanged.
"""

import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models import CustomUser
from cis.models.section import StudentRegistration, ClassSection
from cis.models.student import Student
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear


def _make_section(co_reqs=None):
    """Builds a minimal ClassSection, following the fixture pattern in
    test_pending_sis_mirror.py's make_registration."""
    Group.objects.get_or_create(name='student')
    if not CustomUser.objects.filter(username='cron').exists():
        CustomUser.objects.create_user(
            username='cron', email='cron@example.com', password='x')

    short = uuid.uuid4().hex[:8]
    cohort = Cohort.objects.create(name=f'Cohort-{short}', designator='A')
    course = Course.objects.create(
        catalog_number='001', title='Descriptive Astronomy',
        name=f'A {short}', cohort=cohort)
    ay = AcademicYear.objects.create(name=f'AY-{short}')
    term = Term.objects.create(label=f'Term-{short}', code=short, academic_year=ay)

    # meta={} (no reportingAcademicPeriod) => eligibility gate is skipped.
    section = ClassSection.objects.create(
        course=course, term=term,
        class_number=f'A-{short}', section_number='3428',
        external_sis_id=uuid.uuid4(), meta={},
    )
    if co_reqs:
        section.co_reqs.set(co_reqs)
    return section


def _make_student():
    short = uuid.uuid4().hex[:8]
    student_user = CustomUser.objects.create_user(
        username=f'stu-{short}', email=f'{short}@example.com', password='x',
        first_name='Avi', last_name='Codtest')
    return Student.objects.create(user=student_user, sis_id=uuid.uuid4())


TRIGGER_PATCH_TARGET = (
    'cis.settings.registration_status_email.registration_status_email.from_db'
)


class NeedsMirroringOnCreateTests(TestCase):
    def test_create_at_trigger_status_sets_needs_mirroring(self):
        """Case 1: creating a registration whose status IS in
        sis_mirror_trigger sets needs_mirroring=True and the row shows up in
        pending_sis_mirror()."""
        section = _make_section()
        student = _make_student()

        with patch(TRIGGER_PATCH_TARGET,
                   return_value={'sis_mirror_trigger': ['applied', 'enrolled']}):
            reg = StudentRegistration.objects.create(
                student=student, class_section=section,
                status='applied', status_changed_on={},
            )

        reg.refresh_from_db()
        self.assertTrue(reg.needs_mirroring)

        with patch(TRIGGER_PATCH_TARGET,
                   return_value={'sis_mirror_trigger': ['applied', 'enrolled']}):
            self.assertIn(reg, StudentRegistration.objects.pending_sis_mirror())

    def test_create_at_non_trigger_status_leaves_needs_mirroring_unset(self):
        """Case 2: creating a registration whose status is NOT in the
        trigger list does not set needs_mirroring."""
        section = _make_section()
        student = _make_student()

        with patch(TRIGGER_PATCH_TARGET,
                   return_value={'sis_mirror_trigger': ['enrolled']}):
            reg = StudentRegistration.objects.create(
                student=student, class_section=section,
                status='applied', status_changed_on={},
            )

        reg.refresh_from_db()
        self.assertFalse(reg.needs_mirroring)

    def test_status_change_into_trigger_still_queues(self):
        """Case 3: existing status-change behaviour is unchanged — moving a
        registration into a trigger status still queues it."""
        section = _make_section()
        student = _make_student()

        with patch(TRIGGER_PATCH_TARGET,
                   return_value={'sis_mirror_trigger': ['enrolled']}):
            reg = StudentRegistration.objects.create(
                student=student, class_section=section,
                status='applied', status_changed_on={},
            )
            self.assertFalse(reg.needs_mirroring)

            reg.status = 'enrolled'
            reg.save()

        reg.refresh_from_db()
        self.assertTrue(reg.needs_mirroring)

    def test_coreq_created_by_signal_is_queued_on_same_terms(self):
        """Case 4: a corequisite registration auto-created by the signal
        (created branch calls reg.save(), re-firing this receiver with
        created=True) is queued exactly like its parent."""
        coreq_section = _make_section()
        parent_section = _make_section(co_reqs=[coreq_section])
        student = _make_student()

        with patch(TRIGGER_PATCH_TARGET,
                   return_value={'sis_mirror_trigger': ['applied']}):
            parent_reg = StudentRegistration.objects.create(
                student=student, class_section=parent_section,
                status='applied', status_changed_on={},
            )

        parent_reg.refresh_from_db()
        self.assertTrue(parent_reg.needs_mirroring)

        coreq_reg = StudentRegistration.objects.get(
            student=student, class_section=coreq_section)
        self.assertTrue(coreq_reg.needs_mirroring)

    def test_empty_trigger_setting_queues_nothing_and_does_not_raise(self):
        """Case 5: an empty/missing sis_mirror_trigger setting queues
        nothing and does not raise."""
        section = _make_section()
        student = _make_student()

        with patch(TRIGGER_PATCH_TARGET, return_value={}):
            reg = StudentRegistration.objects.create(
                student=student, class_section=section,
                status='applied', status_changed_on={},
            )

        reg.refresh_from_db()
        self.assertFalse(reg.needs_mirroring)

    def test_save_without_status_change_does_not_read_settings(self):
        """Fix round 1: registration_status_email.from_db() is an
        uncached Setting.objects.get() — a real query on every call. It
        must only run when the created or status-change branch will
        actually consult it, not unconditionally on every save(). Saving
        an existing registration with no status change (the hot path for
        SIS mirror loops, bulk imports, and coreq status-sync updates)
        must not call it at all.

        Chose patch + assert_not_called over assertNumQueries: the
        receiver's created branch does other writes (add_note, coreq
        lookups) whose query count is incidental to this behaviour and
        would make a query-count assertion brittle; asserting the setting
        loader itself was not invoked pins the exact thing being
        guarded.
        """
        section = _make_section()
        student = _make_student()

        with patch(TRIGGER_PATCH_TARGET,
                   return_value={'sis_mirror_trigger': ['enrolled']}):
            reg = StudentRegistration.objects.create(
                student=student, class_section=section,
                status='applied', status_changed_on={},
            )

        with patch(TRIGGER_PATCH_TARGET) as mock_from_db:
            # status is unchanged from the create above, so this save()
            # should not consult sis_mirror_trigger at all.
            reg.save()
            mock_from_db.assert_not_called()
