"""Keep CustomUser.process_campuses in step with campus['process_campus'] (MC-16, #40).

The JSON list is what campus_gate, the staff forms and SAML sign-in read and
write; the M2M mirrors it so a campus's staff can be found with a join, and
so deleting a campus removes its id from every user's list instead of
leaving a stale one. QuerySet.update() bypasses the sync, like any signal;
the next save() catches it up.
"""
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from cis.models.course import Campus
from cis.models.customuser import CustomUser


def listed_campus_ids(user):
    return [str(c) for c in ((user.campus or {}).get('process_campus') or [])]


def _valid_uuids(ids):
    import uuid
    valid = []
    for value in ids:
        try:
            valid.append(uuid.UUID(value))
        except (TypeError, ValueError):
            continue
    return valid


def sync_process_campuses(user):
    ids = listed_campus_ids(user)
    user.process_campuses.set(Campus.objects.filter(id__in=_valid_uuids(ids)))


@receiver(post_save, sender=CustomUser)
def mirror_process_campus(sender, instance, update_fields=None, raw=False, **kwargs):
    if raw or (update_fields is not None and 'campus' not in update_fields):
        return
    sync_process_campuses(instance)


@receiver(pre_delete, sender=Campus)
def forget_deleted_campus(sender, instance, **kwargs):
    campus_id = str(instance.id)
    users = CustomUser.objects.filter(process_campuses=instance) | CustomUser.objects.filter(
        campus__process_campus__contains=campus_id)
    for user in users.distinct():
        perms = dict(user.campus or {})
        perms['process_campus'] = [c for c in listed_campus_ids(user) if c != campus_id]
        if str(perms.get('default_campus') or '') == campus_id:
            perms['default_campus'] = ''
        # update() skips the sync above; the M2M rows go with the campus.
        CustomUser.objects.filter(pk=user.pk).update(campus=perms)
