"""Extra CE staff permission flags (#91).

The staff user form has two fixed Yes/No flags, ``manage_settings`` and
``manage_staff_accounts``. A tenant adds its own by defining ``EXTRA_FLAGS``
in ``services/staff_permissions.py`` of its TENANT_SERVICES_APP::

    EXTRA_FLAGS = [
        ('manage_state_funds', 'Manage State Funds', 'May post state funds.'),
    ]

Each becomes a Yes/No field on the staff user form, is stored in
``CustomUser.campus`` like the built-in two, and is checked with
``user.has_staff_permission('manage_state_funds')``. Without the module there
are no extra flags.
"""
from cis.services.tenant_services import get_tenant_override


# Keys CustomUser.campus already uses; a tenant flag must not overwrite them.
RESERVED_KEYS = frozenset({
    'manage_settings', 'manage_staff_accounts', 'default_campus',
    'process_campus', 'process_campuses',
})


def extra_staff_permission_flags():
    """[(key, label, help_text), ...] from the tenant; [] by default."""
    flags = []
    for flag in get_tenant_override('staff_permissions', 'EXTRA_FLAGS') or ():
        key, label, *rest = flag
        if key in RESERVED_KEYS:
            raise ValueError(
                f'staff_permissions.EXTRA_FLAGS: {key!r} is a built-in key of '
                'CustomUser.campus; pick another name.')
        flags.append((key, label, rest[0] if rest else ''))
    return flags
