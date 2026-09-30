"""CustomUser.process_campuses is the only source of a staff member's campuses (#59).

Read a user's campuses with ``process_campus_ids(user)`` (campus_gate does)
and change them with ``set_process_campuses(user, campuses)`` -- or any
M2M edit, from either side (user.process_campuses / campus.staff_users).

``campus['process_campus']`` is kept for one release as a read-only mirror,
rewritten after every M2M change, so tenant code that still reads it keeps
working. Writing it is refused: a save that changes the list raises
ProcessCampusJSONReadOnly rather than being silently ignored. A user object
loaded before the M2M changed can still be saved -- its stale copy of the
list is replaced by the current one, not written back.
"""
import uuid

from django.db.models.signals import m2m_changed, post_init, post_save, pre_delete, pre_save
from django.dispatch import receiver

from cis.models.course import Campus
from cis.models.customuser import CustomUser

_THROUGH = CustomUser.process_campuses.through
_CACHE = '_process_campus_ids'
_LOADED = '_process_campus_loaded'


class ProcessCampusJSONReadOnly(RuntimeError):
    """campus['process_campus'] was written; it mirrors process_campuses."""


def listed_campus_ids(user):
    """The ids in the user's JSON mirror, as strings."""
    return [str(c) for c in ((user.campus or {}).get('process_campus') or [])]


def _valid_uuids(values):
    valid = []
    for value in values:
        if isinstance(value, Campus):
            valid.append(value.pk)
            continue
        try:
            valid.append(uuid.UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return valid


def _stored_ids(user_pk):
    return [str(pk) for pk in _THROUGH.objects.filter(customuser_id=user_pk)
            .order_by('campus__name').values_list('campus_id', flat=True)]


def process_campus_ids(user):
    """Campus-id strings of the user's campuses, cached on the instance."""
    if getattr(user, 'pk', None) is None:
        return []
    cached = getattr(user, _CACHE, None)
    if cached is None:
        cached = _stored_ids(user.pk)
        setattr(user, _CACHE, cached)
    return list(cached)


def set_process_campuses(user, campuses):
    """Replace the user's campuses. ``campuses``: Campus objects or ids;
    ids of campuses that don't exist are ignored. The user must be saved."""
    user.process_campuses.set(Campus.objects.filter(pk__in=_valid_uuids(campuses)))


def add_process_campuses(user, campuses):
    """Add to the user's campuses, keeping the ones they have. Same
    ``campuses`` shape and rules as set_process_campuses()."""
    user.process_campuses.add(*Campus.objects.filter(pk__in=_valid_uuids(campuses)))


def _mirror(user_pk, instance=None):
    ids = _stored_ids(user_pk)
    perms = CustomUser.objects.filter(pk=user_pk).values_list('campus', flat=True).first()
    perms = dict(perms or {})
    if ids or 'process_campus' in perms:
        perms['process_campus'] = ids
        # update(): no save signals, so the read-only check doesn't fire.
        CustomUser.objects.filter(pk=user_pk).update(campus=perms)
    if instance is not None:
        instance.campus = perms
        setattr(instance, _CACHE, ids)
        setattr(instance, _LOADED, list(ids))


@receiver(m2m_changed, sender=_THROUGH)
def mirror_m2m_change(sender, instance, action, reverse, pk_set, **kwargs):
    if not reverse:
        if action in ('post_add', 'post_remove', 'post_clear'):
            _mirror(instance.pk, instance)
        return
    # campus.staff_users.<op>(...): instance is the campus.
    if action == 'pre_clear':
        instance._clearing_staff = list(
            _THROUGH.objects.filter(campus_id=instance.pk).values_list('customuser_id', flat=True))
    elif action in ('post_add', 'post_remove'):
        for user_pk in pk_set or ():
            _mirror(user_pk)
    elif action == 'post_clear':
        for user_pk in getattr(instance, '_clearing_staff', ()):
            _mirror(user_pk)


@receiver(post_init, sender=CustomUser)
def remember_loaded_list(sender, instance, **kwargs):
    setattr(instance, _LOADED, listed_campus_ids(instance))


@receiver(pre_save, sender=CustomUser)
def refuse_json_writes(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw or (update_fields is not None and 'campus' not in update_fields):
        return
    listed = listed_campus_ids(instance)
    if instance._state.adding:
        changed = bool(listed)
    else:
        changed = listed != getattr(instance, _LOADED, listed)
    if changed:
        raise ProcessCampusJSONReadOnly(
            "campus['process_campus'] is read-only; use "
            "set_process_campuses(user, campuses) or user.process_campuses "
            "(package-cis #59).")
    if instance._state.adding:
        return
    # Unchanged here, but maybe stale: write back the current list.
    ids = _stored_ids(instance.pk)
    if ids or 'process_campus' in (instance.campus or {}):
        instance.campus = dict(instance.campus or {}, process_campus=ids)
    setattr(instance, _CACHE, ids)


@receiver(post_save, sender=CustomUser)
def reset_loaded_list(sender, instance, **kwargs):
    setattr(instance, _LOADED, listed_campus_ids(instance))


@receiver(pre_delete, sender=Campus)
def forget_deleted_campus(sender, instance, **kwargs):
    """The M2M rows go with the campus without an m2m_changed signal, so
    rewrite each affected user's mirror (and default_campus) here."""
    campus_id = str(instance.id)
    users = CustomUser.objects.filter(process_campuses=instance) | CustomUser.objects.filter(
        campus__default_campus=campus_id)
    for user_pk, perms in users.distinct().values_list('pk', 'campus'):
        perms = dict(perms or {})
        if 'process_campus' in perms:
            perms['process_campus'] = [c for c in _stored_ids(user_pk) if c != campus_id]
        if str(perms.get('default_campus') or '') == campus_id:
            perms['default_campus'] = ''
        CustomUser.objects.filter(pk=user_pk).update(campus=perms)
