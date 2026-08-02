# Backward compatibility - settings moved to future_sections app
# This module re-exports the settings form for existing imports


import importlib.util
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.settings.future_sections import future_sections
else:
    from future_sections.settings.future_sections import future_sections

__all__ = ['future_sections']
