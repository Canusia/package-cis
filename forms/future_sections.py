# Backward compatibility - forms moved to future_sections app
# This module re-exports all forms for existing imports

import importlib.util
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.forms import (
        SearchInstructorByCohortForm,
        ConfirmHighSchoolAdministratorsForm,
        ConfirmClassSectionsForm,
        TeacherCourseSectionForm,
        HSAdministratorPositionForm,
        CourseTitleChoiceField,
        AddNewTeacherForm,
        TeacherCourseTeachingForm,
        TeacherCourseBaseLinkFormSet,
        TeacherCourseNotTeachingForm,
    )
else:
    from future_sections.forms import (
        SearchInstructorByCohortForm,
        ConfirmHighSchoolAdministratorsForm,
        ConfirmClassSectionsForm,
        TeacherCourseSectionForm,
        HSAdministratorPositionForm,
        CourseTitleChoiceField,
        AddNewTeacherForm,
        TeacherCourseTeachingForm,
        TeacherCourseBaseLinkFormSet,
        TeacherCourseNotTeachingForm,
    )

__all__ = [
    'SearchInstructorByCohortForm',
    'ConfirmHighSchoolAdministratorsForm',
    'ConfirmClassSectionsForm',
    'TeacherCourseSectionForm',
    'HSAdministratorPositionForm',
    'CourseTitleChoiceField',
    'AddNewTeacherForm',
    'TeacherCourseTeachingForm',
    'TeacherCourseBaseLinkFormSet',
    'TeacherCourseNotTeachingForm',
]
