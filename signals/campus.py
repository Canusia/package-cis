"""Campus-owned records must carry a campus in multi-campus mode (MC-09, #33).

Course, ClassSection and AcademicYear saved without a campus take the campus
the code is serving -- the request host's (CampusMiddleware) or --campus for a
command (CampusCommand) -- so every importer and form path is covered without
changing each one. With no campus in context either, the save is refused:
on a shared deployment an un-campused course would be visible on both
colleges' hosts (campus_gate treats null as shared).

Single-campus mode is untouched: null still means "shared", and nothing is
filled in. QuerySet.update() and bulk_create() bypass this, like any signal.
"""
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver

from cis.campus_context import current_campus_or_none, is_multi_campus
from cis.models.course import Course
from cis.models.section import ClassSection
from cis.models.term import AcademicYear


@receiver(pre_save, sender=Course)
@receiver(pre_save, sender=ClassSection)
@receiver(pre_save, sender=AcademicYear)
def require_campus_in_multi_campus_mode(sender, instance, **kwargs):
    if instance.campus_id is not None or not is_multi_campus():
        return
    campus = current_campus_or_none()
    if campus is None:
        raise ValidationError(
            f'{sender.__name__} needs a campus when MULTI_CAMPUS is on. Set one, '
            f'or save inside cis.campus_context.campus_context(campus).')
    instance.campus = campus
