"""
CIS Models
"""
from .customuser import CustomUser
from .district import District
from .highschool import (
    HighSchool, HighSchoolClassOffering,
    HighSchoolCollegeAdvisor
)

from .teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from .highschool_administrator import (
    HSAdministrator, HSPosition, HSAdministratorPosition,
    HSAdministratorAccessRequest
)
from .term import AcademicYear, Term
from .course import (
    Campus, Cohort, Category, Department, College,
    Course
)

# Note: FutureProjection, FutureCourse, FutureSection models are in cis.models.future_sections
# New models are also in future_sections.models (for new tables)
from .future_sections import (
    FutureCourse, FutureSection
)

from .tech_center_staff import TechCenterStaff

from .student import Student
from .section import (
    SectionNumber,
    ClassSection, StudentRegistration,
    ClassSectionSyllabi
)

# from .teacher_applicant import (
#     TeacherApplicant,
#     TeacherApplication
# )

from .note import TeacherNote
from .event import (
    Venue, Speaker, Event,
    EventAttendee, EventCohort,
    EventItem, EventSpeaker
)

from .faculty import (
    FacultyCoordinator, FacultyCourseCoordinator
)

from .crontab import CronTab

# from .highschool_application import (
#     HighSchoolApplication,
#     HighSchoolInterestedCourse
# )
from .sis import SIS_Subscription
from .student_import import StudentImportBatch, StudentImportRow
from .bulk_enroll import BulkEnrollBatch, BulkEnrollRow
