"""Format of the student data export (#114 item 5), tenant-overridable.

``export_student_data`` (and the Undup Students report) write one row per
pending student. The package writes the CSV it always has. A tenant changes
the format with ``services/student_export.py`` in its TENANT_SERVICES_APP,
defining any of:

- ``HEADERS``: the header row (list of strings);
- ``build_row(record, imported_at)``: the cells for one ``Student``, in
  ``HEADERS`` order;
- ``CSV_OPTIONS``: keyword arguments for ``csv.writer`` (nnu: ``{'delimiter':
  '|', 'quoting': csv.QUOTE_ALL, 'lineterminator': '\\n'}``).

``HEADERS`` and ``build_row`` go together: override both or neither. Where
the file goes (SFTP or the tenant's S3 bucket) is chosen in the
student_exporter setting, not here.
"""
from cis.services.tenant_services import get_tenant_override


def export_format(default_headers, default_build_row):
    """(headers, build_row, csv_options), the tenant's or the defaults."""
    headers = get_tenant_override('student_export', 'HEADERS')
    build_row = get_tenant_override('student_export', 'build_row')
    if (headers is None) != (build_row is None):
        raise ValueError(
            'services/student_export.py must define HEADERS and build_row together.')
    options = get_tenant_override('student_export', 'CSV_OPTIONS') or {'delimiter': ','}
    if headers is None:
        return default_headers, default_build_row, options
    return list(headers), build_row, options
