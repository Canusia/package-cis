"""Faculty coordinator role access.

Same shape as cis.services.instructor_role and cis.services.student_role: the
`faculty` group is granted on account creation (FacultyCoordinator.save()) and
tracks a FacultyCoordinator record's existence, not an active status field, so
there is no signal that revokes it automatically. Deleting the
FacultyCoordinator record never deletes the CustomUser; revoking the group is
a separate explicit step -- cis.services.role_access.revoke_access.
"""
from cis.services.role_access import RoleAccessPolicy

FACULTY = RoleAccessPolicy(
    group_name='faculty',
    record_model_path='cis.FacultyCoordinator',
)
