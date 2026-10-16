"""Long upload names with inner periods must still save (Canusia/package-cis#73).

Django's get_available_name takes the extension from PurePath(name).suffixes,
so every period counts. "HIS 103 SYllabus - T. Little - ... 2026.docx" is read
as a 20-character root plus a ~50-character "extension". Django shortens only
the root, the root runs out before the name fits max_length, and the upload
raises SuspiciousFileOperation.
"""
import datetime
import types
import uuid

from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.test import SimpleTestCase

from cis import utils
from cis.models.crontab import CronLog, cron_log_upload_path
from cis.models.course import CourseUpload
from cis.models.highschool import HighSchoolTranscript
from cis.models.note import StudentNote, TeacherNote
from cis.models.section import ClassSectionSyllabi
from cis.models.student import (
    StudentRecommendation,
    StudentSupportingDocument,
    StudentTuitionAssistanceDocument,
)
from cis.models.teacher import TeacherUpload
from cis.models.teacher_applicant import ApplicantRecommendation, ApplicationUpload

ISSUE_FILENAMES = (
    'HIS 103 SYllabus - T. Little - Fall 2026 Syllabus - October 2026.docx',
    'HIS 103 SYllabus - T. Little - Fall 2026 Syllabus - October 2026.pdf',
)

UPLOAD_PATH_HELPERS = sorted(
    name for name in dir(utils)
    if name.endswith('_upload_path') and callable(getattr(utils, name))
)

# (model, field name) for every cis private-media FileField. ClassSection.syllabi
# is left out: the ClassSection.syllabi property shadows it, so it is not a
# real field.
MEDIA_FIELDS = (
    (ApplicantRecommendation, 'upload'),
    (ApplicationUpload, 'upload'),
    (ClassSectionSyllabi, 'media'),
    (CourseUpload, 'media'),
    (CronLog, 'log_file'),
    (HighSchoolTranscript, 'media'),
    (StudentNote, 'media'),
    (StudentRecommendation, 'upload'),
    (StudentSupportingDocument, 'media'),
    (StudentTuitionAssistanceDocument, 'media'),
    (TeacherNote, 'media'),
    (TeacherUpload, 'media'),
)


class SafeUploadFilename(SimpleTestCase):

    def test_inner_periods_collapse_to_one_extension(self):
        self.assertEqual(
            utils.safe_upload_filename(ISSUE_FILENAMES[0]),
            'HIS_103_SYllabus_-_T_Little_-_Fall_2026_Syllabus_-_October_2026.docx',
        )

    def test_keeps_only_last_suffix(self):
        self.assertEqual(utils.safe_upload_filename('a.b.c.pdf'), 'a_b_c.pdf')
        self.assertEqual(utils.safe_upload_filename('archive.tar.gz'), 'archive_tar.gz')

    def test_strips_directories(self):
        self.assertEqual(utils.safe_upload_filename('../../etc/passwd.txt'), 'passwd.txt')
        self.assertEqual(utils.safe_upload_filename('C:\\x\\y.pdf'), 'C_x_y.pdf')

    def test_empty_root_falls_back(self):
        self.assertEqual(utils.safe_upload_filename('!!!.pdf'), 'file.pdf')
        self.assertEqual(utils.safe_upload_filename('...'), 'file')
        self.assertEqual(utils.safe_upload_filename(''), 'file')

    def test_no_extension(self):
        self.assertEqual(utils.safe_upload_filename('README'), 'README')

    def test_plain_name_unchanged(self):
        self.assertEqual(utils.safe_upload_filename('syllabus_2026.pdf'), 'syllabus_2026.pdf')


class LongDottedUploadNames(SimpleTestCase):

    def setUp(self):
        self.instance = types.SimpleNamespace(
            id=uuid.UUID('a79f09ed-0071-409e-9d0b-08fe5cf3aeb3')
        )

    def store_twice(self, name, max_length):
        """Save `name` twice, the second time through Django's collision path."""
        storage = InMemoryStorage()
        stored = []
        for _ in range(2):
            available = storage.get_available_name(name, max_length=max_length)
            storage.save(available, ContentFile(b'x'))
            stored.append(available)
        return stored

    def test_raw_name_fails_without_the_fix(self):
        """Pins the root cause: the unsanitized path cannot be shortened to 100."""
        storage = InMemoryStorage()
        now = datetime.datetime.now().strftime('%Y/%m')
        raw = (f'syllabus/{now}/{self.instance.id}/'
               + storage.get_valid_name(ISSUE_FILENAMES[0]))

        with self.assertRaises(SuspiciousFileOperation):
            storage.get_available_name(raw, max_length=100)

    def test_every_helper_fits_255(self):
        for helper_name in UPLOAD_PATH_HELPERS:
            for filename in ISSUE_FILENAMES:
                with self.subTest(helper=helper_name, filename=filename):
                    name = getattr(utils, helper_name)(self.instance, filename)
                    self.assertLessEqual(
                        len(name) + utils.UPLOAD_NAME_SUFFIX_LENGTH, 255)
                    for stored in self.store_twice(name, 255):
                        self.assertLessEqual(len(stored), 255)
                        self.assertTrue(stored.endswith(filename.rsplit('.', 1)[1]))

    def test_every_helper_still_fits_a_100_char_field(self):
        """Other packages put these helpers on default (100) FileFields."""
        for helper_name in UPLOAD_PATH_HELPERS:
            for filename in ISSUE_FILENAMES:
                with self.subTest(helper=helper_name, filename=filename):
                    name = getattr(utils, helper_name)(self.instance, filename)
                    for stored in self.store_twice(name, 100):
                        self.assertLessEqual(len(stored), 100)
                        self.assertTrue(stored.endswith(filename.rsplit('.', 1)[1]))

    def test_syllabus_keeps_readable_name(self):
        name = utils.syllabus_upload_path(self.instance, ISSUE_FILENAMES[0])

        self.assertTrue(name.endswith(
            '/HIS_103_SYllabus_-_T_Little_-_Fall_2026_Syllabus_-_October_2026.docx'))

    def test_cron_log_upload_path(self):
        self.assertEqual(
            cron_log_upload_path(self.instance, 'log.json'),
            f'cron_logs/{self.instance.id}/log.json',
        )
        self.assertEqual(
            cron_log_upload_path(self.instance, 'a.b.json'),
            f'cron_logs/{self.instance.id}/a_b.json',
        )


class MediaFieldMaxLength(SimpleTestCase):

    def test_media_fields_allow_255(self):
        for model, field_name in MEDIA_FIELDS:
            with self.subTest(model=model.__name__, field=field_name):
                self.assertEqual(model._meta.get_field(field_name).max_length, 255)
