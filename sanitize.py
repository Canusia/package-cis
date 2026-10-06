"""
Targets and pure helpers for the ``sanitize_db`` management command.

``sanitize_db`` randomizes PII in a *copy* of a tenant database. This module
holds everything that does not touch the database, so it can be unit-tested
without Faker and without a ``*_sanitized`` database:

* the safety guard (``check_guards``),
* the recursive JSON scrubber, the secret blanker and the embedded-email
  rewriter,
* the target registry: which ``(table, column, kind)`` triples are rewritten
  and which tables are truncated.

Extending the targets
---------------------
Tables that belong to another package or to one tenant are added either from
that package's ``AppConfig.ready()``::

    from cis import sanitize
    sanitize.register_columns([('employer_employee', 'email', 'email')])
    sanitize.register_truncate(['employer_accesslog'])

or from the tenant's Django settings::

    SANITIZE_DB_EXTRA = {
        'columns': [('support_ticket_ticket', 'message', 'lorem')],
        'truncate': ['payment_gateway_paymentlog'],
    }

A target whose table or column does not exist is skipped, so the lists are
safe to share across tenants with different apps and schemas.
"""
import hashlib
import re

SAFE_DEPLOY_TYPES = ('local', 'dev')
SANITIZED_DB_SUFFIX = '_sanitized'
DEFAULT_KEEP_DOMAINS = ('@canusia.com',)
SIGNATURE_ON_FILE = 'Signature on file'

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
DATE_RE = re.compile(r'^\d{1,4}[/-]\d{1,2}[/-]\d{1,4}')
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
FAKE_EMAIL_RE = re.compile(r'@example\.(com|net|org)$', re.I)
SECRET_KEY_RE = re.compile(
    r'(secret|password|passwd|token|api[_-]?key|access[_-]?key|private|client[_-]?id|'
    r'auth[_-]?token|account[_-]?sid|webhook|credential|smtp[_-]?user|smtp[_-]?pass)', re.I)

# --------------------------------------------------------------------------- kinds
# Every column target is (table, column, kind). Kinds:
#   lorem                 filler sentence of similar length
#   name, first_name, last_name, email, phone, street, city, zip
#                         a fresh fake value per row
#   signature             'Signature on file'
#   blank                 NULL when the column is nullable, '' otherwise
#   upload                'redacted/<table>/<uuid><ext>' (original filenames hold names)
#   unique_digits         a random digit string, unique within the column
#   json                  recursive scrub (scrub_json)
#   json_clear            {}
#   json_secrets          blank values under secret-looking keys (blank_secrets)
#   embedded_emails       text: every address -> stable fake (keep-domains kept)
#   embedded_emails_json  same, walked through a JSON document
KINDS = frozenset({
    'lorem', 'name', 'first_name', 'last_name', 'email', 'phone', 'street', 'city', 'zip',
    'signature', 'blank', 'upload', 'unique_digits',
    'json', 'json_clear', 'json_secrets', 'embedded_emails', 'embedded_emails_json',
})

# cis_customuser and cis_student are handled by dedicated steps in the command
# (keep-domain, email == username, DOB keeps its year, demographic shuffle);
# their column sets are filtered to what the table actually has.
CUSTOMUSER_FAKE_COLUMNS = ('first_name', 'last_name', 'username', 'email', 'psid', 'address1',
                           'city', 'postal_code', 'primary_phone', 'date_of_birth', 'password')
CUSTOMUSER_BLANK_COLUMNS = ('middle_name', 'suffix', 'previous_names', 'alt_email', 'alt_username',
                            'secondary_email', 'ssn', 'address2', 'po_box', 'county',
                            'secondary_phone', 'alt_phone', 'country_of_birth',
                            'education_background')
STUDENT_ID_COLUMNS = ('student_id', 'pidm', 'state_id')
STUDENT_PARENT_COLUMNS = {
    'parent_first_name': 'first_name', 'parent_last_name': 'last_name',
    'parent_email': 'email', 'parent_phone': 'phone', 'parent_cellphone': 'phone',
}
STUDENT_BLANK_COLUMNS = ('middle_name', 'preferred_name')
STUDENT_SHUFFLE_COLUMNS = (
    'gender', 'gender_designation', 'gender_identity', 'gender_pronoun', 'hispanic',
    'hispanic_background', 'ethnicity', 'race', 'citizenship', 'frl', 'first_gen_student',
    'parent1_education_level', 'parent2_education_level',
)

# simple_history copies: after the live rows are sanitized, these columns are
# copied from the live row onto every history row; orphan history rows (live
# row deleted) are removed.
HISTORY_SYNC = [
    ('cis_historicalcustomuser', 'cis_customuser',
     CUSTOMUSER_FAKE_COLUMNS + CUSTOMUSER_BLANK_COLUMNS),
    ('cis_historicalstudent', 'cis_student',
     STUDENT_ID_COLUMNS + tuple(STUDENT_PARENT_COLUMNS) + STUDENT_BLANK_COLUMNS
     + STUDENT_SHUFFLE_COLUMNS + ('meta',)),
]

_LOREM = [
    # notes
    'cis_studentnote', 'cis_teachernote', 'cis_hsadministratornote', 'cis_classsectionnote',
    'cis_coursenote', 'cis_highschoolnote', 'cis_teacherapplicationnote', 'cis_eventnote',
    'cis_facultycoordinatornote', 'cis_classvisitreportnote', 'cis_studentdroprequest',
    'cis_studentregistration', 'cis_historicalstudentregistration', 'cis_teachercoursecertificate',
    'cis_applicantschoolcourse', 'instructor_app_teacherapplicationnote',
    'instructor_app_applicantschoolcourse', 'drop_wd_dropwdrequest',
]
DEFAULT_COLUMNS = (
    [(t, 'note', 'lorem') for t in _LOREM]
    + [
        ('drop_wd_dropwdrequest', 'ce_note', 'lorem'),
        ('cis_teacher', 'orientation_note', 'lorem'),
        ('class_visit_visitreport', 'teacher_discussion', 'lorem'),
        ('class_visit_visitreport', 'student_discussion', 'lorem'),
        ('class_visit_visitreport', 'liaison_comments', 'lorem'),
        ('class_visit_visitreport', 'visit_letter', 'lorem'),
        ('class_visit_visitreport', 'instructor_response', 'lorem'),
        ('alerts_alert', 'message', 'lorem'),
        ('cis_studentsupportingdocument', 'description', 'lorem'),
        ('cis_teacherupload', 'description', 'lorem'),
        ('cis_studenttuitionassistancedocument', 'description', 'lorem'),
        ('cis_highschooltranscript', 'description', 'lorem'),
        ('cis_studentsiserror', 'message', 'lorem'),

        # signatures
        ('cis_studentagreement', 'student_signature', 'signature'),
        ('cis_studentferpa', 'student_signature', 'signature'),
        ('cis_parentconsent', 'parent_signature', 'signature'),
        ('drop_wd_dropwdrequest', 'student_signature', 'signature'),
        ('drop_wd_dropwdrequest', 'parent_signature', 'signature'),
        ('drop_wd_dropwdrequest', 'instructor_signature', 'signature'),
        ('drop_wd_dropwdrequest', 'counselor_signature', 'signature'),
        ('class_visit_visitreport', 'instructor_signature', 'signature'),

        # contact fields outside cis_customuser / cis_student
        ('cis_parentconsent', 'parent_name', 'name'),
        ('cis_parentconsent', 'parent_email', 'email'),
        ('cis_parentconsent', 'parent_phone', 'phone'),
        ('cis_studentcampusid', 'user_id', 'unique_digits'),
        ('cis_studentcampusid', 'username', 'email'),
        ('cis_studentcampusid', 'email', 'email'),
        ('cis_bulkenrollrow', 'email', 'email'),
        ('cis_hsadministratoraccessrequest', 'name', 'name'),
        ('cis_hsadministratoraccessrequest', 'email', 'email'),
        ('cis_hsadministratoraccessrequest', 'phone', 'phone'),
        ('cis_hsadministratoraccessrequest', 'approver_name', 'name'),
        ('cis_hsadministratoraccessrequest', 'approver_email', 'email'),
        ('cis_hsadministratoraccessrequest', 'approver_phone', 'phone'),
        ('cis_hsadministratoraccessrequest', 'message', 'lorem'),
        ('form_1098t', 'student_name', 'name'),
        ('form_1098t', 'student_address', 'street'),
        ('sp_idp', 'private_key', 'blank'),
        ('sp_idp', 'saml_settings', 'blank'),
        ('sp_idp', 'contact_name', 'name'),
        ('sp_idp', 'contact_email', 'email'),

        # JSON documents
        ('cis_student', 'meta', 'json'),
        ('cis_studentrecommendation', 'recommendation', 'json'),
        ('cis_teacherapplication', 'misc_info', 'json'),
        ('cis_applicantschoolcourse', 'misc_info', 'json'),
        ('cis_applicantcoursereviewer', 'misc_info', 'json'),
        ('cis_studentnote', 'meta', 'json'),
        ('cis_teachernote', 'meta', 'json'),
        ('cis_classsectionnote', 'meta', 'json'),
        ('cis_teacherapplicationnote', 'meta', 'json'),
        ('cis_classvisitreportnote', 'meta', 'json'),
        ('cis_hsadministratorposition', 'meta', 'json'),
        ('cis_studentsiserror', 'match_results', 'json'),
        ('cis_studentimportrow', 'raw_data', 'json'),
        ('instructor_app_teacherapplication', 'misc_info', 'json'),
        ('instructor_app_applicantschoolcourse', 'misc_info', 'json'),
        ('instructor_app_applicantcoursereviewer', 'misc_info', 'json'),
        ('instructor_app_teacherapplicant', 'meta', 'json'),
        ('instructor_app_teacherapplicationnote', 'meta', 'json'),
        ('class_visit_visitreport', 'meta', 'json'),
        ('class_visit_visitschedule', 'meta', 'json'),
        ('drop_wd_dropwdrequest', 'notes', 'json'),
        ('pd_event_eventattendee', 'meta', 'json'),
        ('report_reportscheduler', 'summary', 'json_clear'),  # pre-signed S3 download links
        ('socialaccount_socialaccount', 'extra_data', 'json_clear'),

        # contact addresses embedded in content, and secrets in settings
        ('announcement_announcement', 'description', 'embedded_emails'),
        ('cis_futurecourse', 'section_info', 'embedded_emails_json'),
        ('cis_setting', 'value', 'embedded_emails_json'),
        ('cis_historicalsetting', 'value', 'embedded_emails_json'),
        ('cis_setting', 'value', 'json_secrets'),
        ('cis_historicalsetting', 'value', 'json_secrets'),

        # uploads
        ('cis_studentnote', 'media', 'upload'),
        ('cis_teachernote', 'media', 'upload'),
        ('cis_teacherupload', 'media', 'upload'),
        ('cis_studentsupportingdocument', 'media', 'upload'),
        ('cis_studenttuitionassistancedocument', 'media', 'upload'),
        ('cis_highschooltranscript', 'media', 'upload'),
        ('cis_studentrecommendation', 'upload', 'upload'),
        ('cis_applicationupload', 'upload', 'upload'),
        ('cis_applicantrecommendation', 'upload', 'upload'),
        ('instructor_app_applicationupload', 'upload', 'upload'),
        ('instructor_app_applicantrecommendation', 'upload', 'upload'),
        ('class_visit_visitreportfile', 'file', 'upload'),
    ]
)

DEFAULT_TRUNCATE = [
    # email bodies, sessions, credentials, logs and queues
    'mailer_message', 'mailer_messagelog', 'mailer_dontsendentry',
    'django_session', 'authtoken_token', 'impersonate_impersonationlog', 'django_admin_log',
    'axes_accesslog', 'axes_accessattempt', 'axes_accessfailurelog',
    'django_login_history_login', 'django_tasks_database_dbtaskresult',
    'ses_tracking_emailevent', 'ses_tracking_bounce', 'ses_tracking_complaint',
    'ses_tracking_sesevent',
    'cis_sis_log', 'ethos_ethoslog', 'student_emailchangerequest',
    'sp_idpattributelog', 'sp_idpuser',
]

_extra_columns = []
_extra_truncate = []


def register_columns(entries):
    """Add (table, column, kind) targets. Call from an AppConfig.ready()."""
    entries = [tuple(e) for e in entries]
    for entry in entries:
        validate_column_target(entry)
    _extra_columns.extend(e for e in entries if e not in _extra_columns)


def register_truncate(tables):
    """Add tables to truncate. Call from an AppConfig.ready()."""
    _extra_truncate.extend(t for t in tables if t not in _extra_truncate)


def validate_column_target(entry):
    if len(entry) != 3 or entry[2] not in KINDS:
        raise ValueError(f'sanitize_db target {entry!r} must be (table, column, kind) '
                         f'with kind in {sorted(KINDS)}')


def column_targets(extra_setting=None):
    """Defaults + registered + SANITIZE_DB_EXTRA['columns'], de-duplicated, in order."""
    from_setting = [tuple(e) for e in (extra_setting or {}).get('columns', [])]
    for entry in from_setting:
        validate_column_target(entry)
    seen, out = set(), []
    for entry in list(DEFAULT_COLUMNS) + _extra_columns + from_setting:
        if entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out


def truncate_targets(extra_setting=None):
    seen, out = set(), []
    for table in DEFAULT_TRUNCATE + _extra_truncate + list((extra_setting or {}).get('truncate', [])):
        if table not in seen:
            seen.add(table)
            out.append(table)
    return out


# --------------------------------------------------------------------------- guard
def check_guards(deploy_type, db_name):
    """Return None when it is safe to rewrite this database, else the reason it is not."""
    if deploy_type not in SAFE_DEPLOY_TYPES:
        return f'Refusing to run with DEPLOY_TYPE={deploy_type!r}; allowed: {SAFE_DEPLOY_TYPES}.'
    if not str(db_name or '').endswith(SANITIZED_DB_SUFFIX):
        return (f'Refusing to run on database {db_name!r}: its name must end with '
                f'{SANITIZED_DB_SUFFIX!r}. Copy the database first.')
    return None


# --------------------------------------------------------------------------- scrubbers
# ``fake`` is anything with Faker's email(), name(), sentence(nb_words=) and
# numerify() methods; tests pass a stub.
def phone(fake):
    return fake.numerify('(###)###-####')


def lorem_like(text, fake):
    return fake.sentence(nb_words=max(3, min(60, len(str(text).split()))))


def scrub_value(key, val, fake):
    if not isinstance(val, str) or not val.strip():
        return val
    k = (key or '').lower()
    if UUID_RE.match(val) or DATE_RE.match(val):
        return val
    if 'email' in k or EMAIL_RE.search(val):
        return fake.email()
    if 'phone' in k or 'cell' in k:
        return phone(fake)
    if k.endswith('name') or k.startswith('recommender_name') or k == 'approver':
        return fake.name()
    if len(val) > 40 and ' ' in val:
        return lorem_like(val, fake)
    return val


def scrub_json(obj, fake, key=None):
    """Recursively replace emails, phones, ``*name`` values and long free text."""
    if isinstance(obj, dict):
        return {k: scrub_json(v, fake, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_json(v, fake, key) for v in obj]
    return scrub_value(key, obj, fake)


def blank_secrets(obj):
    """Return (copy, hits) with scalar values under secret-looking keys set to ''.

    Values are never returned to the caller other than inside the copy, so the
    command can report a count without printing a secret.
    """
    if isinstance(obj, dict):
        out, hits = {}, 0
        for k, v in obj.items():
            if (isinstance(k, str) and SECRET_KEY_RE.search(k)
                    and isinstance(v, (str, int, float)) and not isinstance(v, bool)
                    and str(v) != ''):
                out[k] = ''
                hits += 1
            else:
                out[k], h = blank_secrets(v)
                hits += h
        return out, hits
    if isinstance(obj, list):
        res = [blank_secrets(v) for v in obj]
        return [r[0] for r in res], sum(r[1] for r in res)
    return obj, 0


def fake_email_for(address):
    """A stable fake per real address, so the same contact maps to the same fake everywhere."""
    return 'contact-' + hashlib.sha1(address.lower().encode()).hexdigest()[:10] + '@example.com'


def is_kept_email(address, keep_domains=DEFAULT_KEEP_DOMAINS):
    a = address.lower()
    return bool(FAKE_EMAIL_RE.search(a)) or any(a.endswith(d.lower()) for d in keep_domains)


def replace_embedded_emails(obj, keep_domains=DEFAULT_KEEP_DOMAINS):
    """Rewrite every email address inside a string or JSON document."""
    if isinstance(obj, dict):
        return {k: replace_embedded_emails(v, keep_domains) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace_embedded_emails(v, keep_domains) for v in obj]
    if isinstance(obj, str):
        return EMAIL_RE.sub(
            lambda m: m.group(0) if is_kept_email(m.group(0), keep_domains) else fake_email_for(m.group(0)),
            obj)
    return obj
