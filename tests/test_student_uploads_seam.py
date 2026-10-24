"""Tenant uploads on the Manage Students page (#96): UPLOADS in the tenant's
services/student_uploads.py render as cards and their POSTs reach the
tenant's handler. Without the module the page is unchanged."""
from unittest import mock

from django import forms
from django.http import HttpResponse
from django.urls import reverse

from cis.services import student_uploads
from cis.tests.test_student_add_new_page import AddNewPageTests as _Base


class EduidForm(forms.Form):
    file = forms.FileField(label='EDUID file')


def _handler(request):
    return HttpResponse(f"handled {request.FILES['file'].name}")


UPLOADS = [{'action': 'import_eduids', 'title': 'Student EDUID Importer',
            'help': 'Upload a CSV.', 'form': EduidForm, 'handler': _handler,
            'submit_label': 'Import EDUIDs'}]


def _with(uploads):
    return mock.patch.object(
        student_uploads, 'get_tenant_override',
        lambda m, a: uploads if (m, a) == ('student_uploads', 'UPLOADS') else None)


class StudentUploadsSeamTests(_Base):
    test_add_new_links_to_new_importer = None  # covered by the base module

    def test_no_tenant_cards_by_default(self):
        with _with(None):
            body = self.client.get(reverse('cis:student_add_new')).content.decode()
        self.assertNotIn('import_eduids', body)

    def test_tenant_upload_renders_a_card(self):
        with _with(UPLOADS):
            body = self.client.get(reverse('cis:student_add_new')).content.decode()
        self.assertIn('Student EDUID Importer', body)
        self.assertIn('value="import_eduids"', body)
        self.assertIn('Import EDUIDs', body)

    def test_tenant_upload_post_reaches_the_handler(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        with _with(UPLOADS):
            resp = self.client.post(reverse('cis:student_add_new'), {
                'action': 'import_eduids',
                'file': SimpleUploadedFile('ids.csv', b'a,b\n'),
            })
        self.assertEqual(resp.content, b'handled ids.csv')
