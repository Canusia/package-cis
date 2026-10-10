"""Picking a parent term in a CE filter includes its sub-terms."""
from django.test import TestCase

from cis.models.section import StudentRegistration
from cis.models.section import StudentDropRequest
from cis.tests.term_tree_fixtures import TermTreeFixtureMixin, run_viewset
from cis.views.course import CourseViewSet
from cis.views.drop_request import StudentDropViewSet
from cis.views.registration import RegistrationViewSet
from cis.views.section import ClassesRegisteredByCampusViewSet
from cis.views.student import StudentViewSet


class TermFilterTests(TermTreeFixtureMixin, TestCase):
    def reg_labels(self, qs):
        return {r.class_section.term.label for r in qs}

    def test_registrations_parent_includes_sub_terms(self):
        qs = run_viewset(RegistrationViewSet, self.ce, term=str(self.quarter.pk))
        self.assertEqual(self.reg_labels(qs), self.fall_labels())

    def test_registrations_sub_term_is_exact(self):
        qs = run_viewset(RegistrationViewSet, self.ce, term=str(self.semester.pk))
        self.assertEqual(self.reg_labels(qs), {'Fall Semester'})

    def test_registrations_bad_term_still_empty(self):
        self.assertFalse(run_viewset(RegistrationViewSet, self.ce, term='202630').exists())

    def test_students_parent_includes_sub_terms(self):
        qs = run_viewset(StudentViewSet, self.ce, term_id=str(self.quarter.pk))
        expected = {self.registrations[l].student_id for l in self.fall_labels()}
        self.assertEqual({s.pk for s in qs}, expected)

    def test_drop_requests_parent_includes_sub_terms(self):
        drops = {
            label: StudentDropRequest.objects.create(
                registration=reg, student=reg.student)
            for label, reg in self.registrations.items()
        }
        qs = run_viewset(StudentDropViewSet, self.ce, term=str(self.quarter.pk))
        self.assertEqual({d.pk for d in qs},
                         {drops[l].pk for l in self.fall_labels()})

    def test_campus_classes_parent_includes_sub_terms(self):
        qs = run_viewset(ClassesRegisteredByCampusViewSet, self.ce,
                         campus_id=str(self.campus.pk), term_id=str(self.quarter.pk))
        self.assertEqual({s.term.label for s in qs}, self.fall_labels())

    def test_courses_parent_includes_sub_terms(self):
        qs = run_viewset(CourseViewSet, self.ce, term=str(self.quarter.pk))
        self.assertIn(self.course, qs)
        qs = run_viewset(CourseViewSet, self.ce, term=str(self.spring.pk))
        self.assertIn(self.course, qs)
