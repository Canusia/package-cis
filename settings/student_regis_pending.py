"""Backwards-compat shim — the real settings form lives in the
student_onboarding submodule now. Other cis code still imports via this path.
"""
from student_onboarding.settings.student_regis_pending import (  # noqa: F401
    SettingForm,
    student_regis_pending,
)
