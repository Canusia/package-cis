"""
Future Sections views - BACKWARD COMPATIBILITY SHIM

Views have been moved to the future_sections app.
This file provides backward compatibility for existing imports.

New location:
- Views: future_sections.views.ce
- ViewSets: future_sections.views.ce_api
"""

# Backward compatibility - views moved to future_sections app
import importlib.util
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.views.ce import (
        index,
        detail,
        settings,
        delete_section,
        future_sections_actions,
        mark_as_teaching,
        mark_as_not_teaching,
        remove_marked_as_not_teaching,
        send_survey_to_instructors,
    )
    from future_sections.future_sections.views.ce_api import (
        PendingFutureClassSectionViewSet,
        FutureProjectionViewSet,
        FutureClassSectionViewSet,
    )
else:
    from future_sections.views.ce import (
        index,
        detail,
        settings,
        delete_section,
        future_sections_actions,
        mark_as_teaching,
        mark_as_not_teaching,
        remove_marked_as_not_teaching,
        send_survey_to_instructors,
    )
    from future_sections.views.ce_api import (
        PendingFutureClassSectionViewSet,
        FutureProjectionViewSet,
        FutureClassSectionViewSet,
    )

__all__ = [
    'index',
    'detail',
    'settings',
    'delete_section',
    'future_sections_actions',
    'mark_as_teaching',
    'mark_as_not_teaching',
    'remove_marked_as_not_teaching',
    'send_survey_to_instructors',
    'PendingFutureClassSectionViewSet',
    'FutureProjectionViewSet',
    'FutureClassSectionViewSet',
]
