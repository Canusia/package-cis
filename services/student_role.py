"""Student role access.

Same shape as cis.services.instructor_role: the `student` group is granted on
account creation and tracks a `Student` record's existence, not an active
status field, so there is no signal that revokes it automatically. Deleting
the `Student` record never deletes the `CustomUser`; revoking the group is a
separate explicit step -- cis.services.role_access.revoke_access.
"""
from cis.services.role_access import RoleAccessPolicy

STUDENT = RoleAccessPolicy(
    group_name='student',
    record_model_path='cis.Student',
)
