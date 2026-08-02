"""Regression test for cis.utils.get_foreign_key_references (issue #22).

The migrate tab's "select items to move" was blank because a stale ContentType
(`s3_storage_browser.globalpermission`, pk=1 — iterated first) has
`model_class() is None`. The helper called `None._meta.get_fields()`, which
raised AttributeError, and its bare `except:` silently swallowed it and returned
an empty list before any real referencing model was scanned.
"""
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from cis.models.course import Cohort, Course, CourseAppRequirement
from cis.utils import get_foreign_key_references


class GetForeignKeyReferencesStaleContentTypeTests(TestCase):
    def test_stale_contenttype_does_not_truncate_references(self):
        cohort = Cohort.objects.create(name='Co', designator='CO')
        course = Course.objects.create(
            catalog_number='101', title='T', cohort=cohort)
        # A genuine foreign-key reference to the course.
        CourseAppRequirement.objects.create(course=course, name='Req')

        # A stale ContentType whose model no longer exists -> model_class() None.
        ghost = ContentType(app_label='ghost_app', model='ghost_model')
        self.assertIsNone(ghost.model_class())

        # Force the ghost to be scanned FIRST, reproducing production (a stale
        # CT precedes the models that actually reference the instance).
        ordered = [ghost] + list(ContentType.objects.all())
        with patch('cis.utils.ContentType.objects.all', return_value=ordered):
            refs = get_foreign_key_references(course)

        names = {name for name, _ in refs}
        self.assertIn(
            'CourseAppRequirement', names,
            'a stale ContentType with model_class()=None truncated the scan',
        )
