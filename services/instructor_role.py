"""Instructor role access.

Note there is deliberately NO signal removing the `instructor` group when a
teacher's TeacherHighSchool rows all go inactive — unlike high school
administrators, whose group tracks active positions via
cis/signals/highschool_admin.py. Instructors keep portal access until their
Teacher record is deleted and the role explicitly revoked. Adding such a signal
would revoke access at scale for instructors whose schools went inactive; that
is a separate product decision, not part of this fix.
"""
from cis.services.role_access import RoleAccessPolicy

INSTRUCTOR = RoleAccessPolicy(
    group_name='instructor',
    record_model_path='cis.Teacher',
)
