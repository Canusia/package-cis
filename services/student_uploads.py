"""Tenant file uploads on the CE Manage Students page (#96).

The page (/ce/students/add_new) has the package's importers. A tenant adds
its own -- nnu's EDUID import -- by defining ``UPLOADS`` in
``services/student_uploads.py`` of its TENANT_SERVICES_APP::

    UPLOADS = [{
        'action': 'import_eduids',          # unique POST action name
        'title': 'Student EDUID Importer',
        'help': 'Upload a CSV with ...',    # plain text, shown above the form
        'form': EDUIDImportForm,            # a forms.Form with a file field
        'handler': import_eduids_from_file, # handler(request) -> HttpResponse
        'submit_label': 'Import EDUIDs',    # optional
    }]

Each becomes a card with its form, posting back to the page with its
``action``; the page hands that POST to ``handler``. Without the module the
page is unchanged.
"""
from cis.services.tenant_services import get_tenant_override


def tenant_student_uploads():
    return list(get_tenant_override('student_uploads', 'UPLOADS') or ())


def find_upload(action):
    for upload in tenant_student_uploads():
        if upload.get('action') == action:
            return upload
    return None
