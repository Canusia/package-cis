"""
admin models
"""

from .customuser import CustomUserAdmin
from .crontab import CronTabAdmin

from .student import (
    StudentAdmin,
    StudentAgreementAdmin, StudentRecommendationAdmin, ParentConsentAdmin
)

from .course import *
from .section import *
from .teacher import *

from .setting import *

from .sis import *