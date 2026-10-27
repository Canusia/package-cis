"""Sections index "Update Class Status" bulk action (#131 item 4).

Sets ClassSection.status (Active / Cancelled) on the selected sections, through
the same do_bulk_action modal-then-confirm flow as Change Roster Status.
"""
import json

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term


class UpdateClassStatusBulkActionTests(TestCase):

    def setUp(self):
        # django_login_history's receiver needs REMOTE_ADDR, which the test
        # client does not send.
        saved = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        self.addCleanup(setattr, user_logged_in, 'receivers', saved)

        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        cohort = Cohort.objects.create(name='Eng', designator='ENG')
        course = Course.objects.create(
            catalog_number='101', title='Comp', name='ENG 101', cohort=cohort)
        term = Term.objects.create(
            academic_year=AcademicYear.objects.create(name='2026-2027'),
            code='F26', label='Fall 2026')
        teacher = Teacher.objects.create(user=CustomUser.objects.create_user(
            username='teach', email='teach@example.com', password='x'))
        self.a = ClassSection.objects.create(
            course=course, term=term, class_number='91001',
            section_number='001', teacher=teacher)
        self.b = ClassSection.objects.create(
            course=course, term=term, class_number='91002', section_number='002')
        self.untouched = ClassSection.objects.create(
            course=course, term=term, class_number='91003', section_number='003')

        self.ce = CustomUser.objects.create_user(
            username='ce', email='ce@example.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.url = reverse('cis:section_bulk_actions')

    def test_modal_lists_the_selected_sections(self):
        self.client.force_login(self.ce)
        resp = self.client.post(self.url, {
            'action': 'update_class_status',
            'ids[]': [str(self.a.pk), str(self.b.pk)]})
        body = resp.json()
        self.assertEqual(body['outcome'], 'modal')
        self.assertIn('Update Class Status', body['html'])
        self.assertIn('Cancelled', body['html'])
        self.assertIn('(Active)', body['html'])

    def test_confirm_sets_the_status_and_notes_each_section(self):
        self.client.force_login(self.ce)
        resp = self.client.post(self.url, {
            'action': 'update_class_status', 'action_confirmed': '1',
            'record_ids': [str(self.a.pk), str(self.b.pk)], 'new_status': 'C'})
        self.assertEqual(resp.json()['fn'], 'onBulkActionComplete')
        self.assertEqual(
            dict(ClassSection.objects.values_list('class_number', 'status')),
            {'91001': 'C', '91002': 'C', '91003': 'A'})
        self.assertIn('Updated class status to Cancelled',
                      [n.note for n in self.a.classsectionnote_set.all()])

    def test_an_unknown_status_is_rejected(self):
        self.client.force_login(self.ce)
        resp = self.client.post(self.url, {
            'action': 'update_class_status', 'action_confirmed': '1',
            'record_ids': [str(self.a.pk)], 'new_status': 'X'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('new_status', json.loads(resp.json()['errors']))
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, 'A')

    def test_non_ce_user_is_refused(self):
        self.client.force_login(CustomUser.objects.get(username='teach'))
        self.client.post(self.url, {
            'action': 'update_class_status', 'action_confirmed': '1',
            'record_ids': [str(self.a.pk)], 'new_status': 'C'})
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, 'A')

    def test_sections_index_offers_the_button(self):
        self.client.force_login(self.ce)
        resp = self.client.get(reverse('cis:sections'))
        self.assertEqual(resp.status_code, 200)
        actions = resp.context['sections_table']
        self.assertIn('update_class_status', json.dumps(actions, default=str))

    def test_empty_selection_answers_instead_of_500(self):
        self.client.force_login(self.ce)
        resp = self.client.post(self.url, {'action': 'update_class_status'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'error')

    def test_confirm_ignores_a_section_on_a_campus_the_user_cannot_process(self):
        prefix = settings.CAMPUS_CODE_PREFIX
        mine = Campus.objects.create(name='Mine', code=f'{prefix}-mine')
        other = Campus.objects.create(name='Other', code=f'{prefix}-other')
        ClassSection.objects.filter(pk=self.a.pk).update(campus=mine)
        ClassSection.objects.filter(pk=self.b.pk).update(campus=other)
        self.ce.set_process_campuses([str(mine.id)])
        self.client.force_login(self.ce)
        # A forged confirm naming both sections only updates the user's own.
        self.client.post(self.url, {
            'action': 'update_class_status', 'action_confirmed': '1',
            'record_ids': [str(self.a.pk), str(self.b.pk)], 'new_status': 'C'})
        self.assertEqual(
            dict(ClassSection.objects.filter(pk__in=[self.a.pk, self.b.pk])
                 .values_list('class_number', 'status')),
            {'91001': 'C', '91002': 'A'})
