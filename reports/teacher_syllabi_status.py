import io
import csv
import os
import re
import zipfile
import datetime

from django import forms
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.core.files.base import ContentFile

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.backends.storage_backend import PrivateMediaStorage
from cis.models.term import Term
from cis.models.section import ClassSection, ClassSectionSyllabi


STATUS_CHOICES = (
    ('submitted', 'Submitted (Pending Review)'),
    ('needs_update', 'Sent Back for Update'),
    ('approved', 'Approved'),
    ('not_submitted', 'Not Submitted'),
)


def derive_status(section):
    """Return one of: 'submitted', 'needs_update', 'approved', 'not_submitted'.

    Status priority:
      1. If ClassSection.syllabi_status == 'needs update' -> 'needs_update'
         (set on the section when faculty sends the syllabus back; see
         cis/models/section.py:418-431).
      2. Otherwise look at the latest linked ClassSectionSyllabi
         (by -uploaded_on):
           - 'Reviewed'        -> 'approved'
           - 'pending review'  -> 'submitted'
      3. No syllabi linked -> 'not_submitted'.
    """
    if (section.syllabi_status or '').lower() == 'needs update':
        return 'needs_update'

    latest = section.classsectionsyllabi_set.order_by('-uploaded_on').first()
    if latest is None:
        return 'not_submitted'

    if latest.status == 'Reviewed':
        return 'approved'
    if latest.status == 'pending review':
        return 'submitted'
    return 'not_submitted'


class teacher_syllabi_status(forms.Form):

    terms = forms.ModelMultipleChoiceField(
        queryset=None,
        required=True,
        label='Term(s)',
    )

    status = forms.MultipleChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        label='Syllabus Status (leave empty for all)',
    )

    download_files = forms.BooleanField(
        required=False,
        label='Download Files (zip syllabus files + CSV)',
    )

    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

        self.fields['terms'].queryset = Term.objects.all().order_by('-code')

    STATUS_LABEL = dict(STATUS_CHOICES)

    COLUMNS = [
        'Term', 'Term Label', 'High School', 'District',
        'Course', 'Class Number', 'Section',
        'Teacher EMPLID', 'Teacher First Name', 'Teacher Last Name',
        'Teacher Email',
        'Syllabus Status', 'Syllabus Filename',
        'Uploaded On', 'Reviewed On', 'Review Note',
    ]

    def _build_row(self, section, status_key, latest):
        changed = section.syllabi_status_changed_on or {}
        return [
            getattr(section.term, 'code', '') or '',
            getattr(section.term, 'label', '') or '',
            getattr(section.highschool, 'name', '') if section.highschool else '',
            getattr(section.highschool.district, 'name', '')
                if section.highschool and section.highschool.district else '',
            getattr(section.course, 'name', '') if section.course else '',
            section.class_number or '',
            getattr(section, 'section', '') or '',
            getattr(section.teacher.user, 'psid', '') if section.teacher else '',
            section.teacher.user.first_name if section.teacher else '',
            section.teacher.user.last_name if section.teacher else '',
            section.teacher.user.email if section.teacher else '',
            self.STATUS_LABEL.get(status_key, status_key),
            latest.filename if latest else '',
            latest.uploaded_on.strftime('%Y-%m-%d %H:%M')
                if latest and latest.uploaded_on else '',
            changed.get('reviewed_on', '') if isinstance(changed, dict) else '',
            changed.get('note', '') if isinstance(changed, dict) else '',
        ]

    def run(self, task, data):
        terms = data.get('terms')
        wanted = set(data.get('status') or [])  # empty = all
        download_files = bool(data.get('download_files'))

        term_ids = [t.id if hasattr(t, 'id') else t for t in terms]

        sections = ClassSection.objects.filter(
            term__id__in=term_ids,
            teacher__isnull=False,
        ).select_related(
            'teacher__user', 'course', 'highschool',
            'highschool__district', 'term',
        ).prefetch_related('classsectionsyllabi_set').order_by(
            'term__code',
            'highschool__name',
            'teacher__user__last_name',
            'course__name',
            'class_number',
        )

        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        media_storage = PrivateMediaStorage()
        path_prefix = 'reports/' + str(task.id) + '/'

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')
        writer.writerow(self.COLUMNS)

        zip_buffer = io.BytesIO() if download_files else None
        zf = zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) if download_files else None
        used_names = set()

        for section in sections:
            status_key = derive_status(section)
            if wanted and status_key not in wanted:
                continue

            latest = section.classsectionsyllabi_set.order_by('-uploaded_on').first()
            row = self._build_row(section, status_key, latest)
            writer.writerow([force_str(c) for c in row])

            if download_files and latest and latest.media:
                arcname = self._zip_arcname(section, latest, used_names)
                try:
                    latest.media.open('rb')
                    zf.writestr(arcname, latest.media.read())
                except Exception:
                    pass
                finally:
                    try:
                        latest.media.close()
                    except Exception:
                        pass

        if download_files:
            zf.writestr('teacher_syllabi_status_' + timestamp + '.csv', stream.getvalue())
            zf.close()

            zip_name = 'teacher_syllabi_status_' + timestamp + '.zip'
            path = media_storage.save(
                path_prefix + zip_name,
                ContentFile(zip_buffer.getvalue()),
            )
            return media_storage.url(path)

        csv_name = 'teacher_syllabi_status_' + timestamp + '.csv'
        path = media_storage.save(
            path_prefix + csv_name,
            ContentFile(stream.getvalue().encode('utf-8')),
        )
        return media_storage.url(path)

    @staticmethod
    def _zip_arcname(section, syllabi, used_names):
        teacher_last = ''
        if section.teacher and section.teacher.user:
            teacher_last = section.teacher.user.last_name or ''
        course_name = getattr(section.course, 'name', '') or ''
        class_no = section.class_number or ''
        ext = os.path.splitext(syllabi.filename or '')[1] or ''

        base = '_'.join(p for p in [teacher_last, course_name, str(class_no)] if p)
        base = re.sub(r'[^A-Za-z0-9._-]+', '_', base).strip('_') or 'syllabus'

        candidate = 'syllabi/' + base + ext
        n = 2
        while candidate in used_names:
            candidate = 'syllabi/' + base + '_' + str(n) + ext
            n += 1
        used_names.add(candidate)
        return candidate
