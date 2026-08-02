import csv
import io

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from cis.menu import cis_menu, draw_menu
from cis.models.student_import import StudentImportBatch
from cis.forms.student_import import StudentImportUploadForm
from cis.services.importers.student_importer import StudentImporter
from cis.services.importers.student_import_schema import StudentImportColumns

PREVIEW_TEMPLATE = 'cis/students/import_preview.html'
PREVIEW_URL = 'cis:student_import_preview'
CONFIRM_URL = 'cis:student_import_confirm'


def _menu():
    """The CE sidebar, with the Students section active (same as /ce/students)."""
    return draw_menu(cis_menu, 'students', 'students')


def allowed_highschools(request):
    """All active high schools for CE admins (None = importer default)."""
    return None


def import_scope():
    return 'ce'


def download_template(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="student_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(StudentImportColumns.headers())
    return response


def upload(request):
    form = StudentImportUploadForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        decoded = request.FILES['file'].read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded))
        importer = StudentImporter(
            highschools=allowed_highschools(request), scope=import_scope())
        header_errors = importer.header_errors(reader.fieldnames)
        if header_errors:
            return render(request, PREVIEW_TEMPLATE, {
                'header_errors': header_errors,
                'field_definitions': StudentImportColumns.field_definitions(),
                'upload_form': StudentImportUploadForm(),
                'menu': _menu(),
            })
        batch = importer.parse_into_batch(
            reader, created_by=request.user,
            source_filename=request.FILES['file'].name)
        return redirect(PREVIEW_URL, batch_id=batch.id)
    return render(request, PREVIEW_TEMPLATE, {
        'upload_form': form,
        'field_definitions': StudentImportColumns.field_definitions(),
        'menu': _menu(),
    })


def preview(request, batch_id):
    batch = get_object_or_404(StudentImportBatch, pk=batch_id, scope='ce')
    return render(request, PREVIEW_TEMPLATE, {
        'batch': batch,
        'rows': batch.rows.all(),
        'confirm_url': CONFIRM_URL,
        'menu': _menu(),
    })


def confirm(request, batch_id):
    if request.method != 'POST':
        return redirect(PREVIEW_URL, batch_id=batch_id)
    batch = get_object_or_404(StudentImportBatch, pk=batch_id, scope='ce')
    importer = StudentImporter(
        highschools=allowed_highschools(request), scope=import_scope())
    if batch.status == 'committed':
        summary = {'created': 0, 'skipped': batch.rows.count(), 'failed': 0}
    else:
        selected = request.POST.getlist('selected_rows')
        summary = importer.commit(batch, selected)
    return render(request, PREVIEW_TEMPLATE, {
        'batch': batch,
        'rows': batch.rows.all(),
        'summary': summary,
        'committed': True,
        'confirm_url': CONFIRM_URL,
        'menu': _menu(),
    })
