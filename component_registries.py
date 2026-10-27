"""Package defaults for the host's `myce.component_registry.*` modules (#97).

cis views import their tab and action registries from the host's
`myce.component_registry` package. A tenant adopting the package without one
of those modules used to fail the whole cis URLconf. For the registries that
are nothing but empty registries plus an eager import of cis's own tabs and
actions, cis can supply the module itself: `install_defaults()` (run from
`CisConfig.__init__`) registers a stand-in under the host's module name, only
when the host does not ship that module. A host module always wins.

Registries that carry tenant content (course and academic_year wire SIS
actions) have no default; a host missing one is named by system check
cis.W012. So is a host module that lacks a name cis imports from it, and a
host without the base classes (`tabs.TabRegistry`, `ActionRegistry`) the
stand-ins are built from: those stand-ins are then skipped, not fatal.
"""
import importlib
import importlib.machinery
import importlib.util
import sys
import types
from collections import OrderedDict

PACKAGE = 'myce.component_registry'

# Every host registry module cis imports, at module level or per request.
REQUIRED_REGISTRIES = (
    'academic_year', 'access_request', 'class_section', 'class_section_index',
    'course', 'faculty_coordinator', 'highschool', 'hs_administrator',
    'registration', 'student', 'support_docs', 'teacher', 'term',
)

# module -> names cis imports from it ('' is the package itself). Mirrors the
# `from myce.component_registry... import` lines in cis; a guard test keeps
# the two in step.
REQUIRED_NAMES = {
    '': ('ActionRegistry',),
    'tabs': ('TabRegistry',),
    'academic_year': ('academic_year_actions', 'academic_year_tabs'),
    'access_request': ('access_request_tabs',),
    'class_section': ('class_section_tabs',),
    'class_section_index': ('class_section_index_tabs',),
    'course': ('course_actions', 'course_tabs'),
    'faculty_coordinator': ('faculty_coordinator_tabs',),
    'highschool': ('highschool_actions', 'highschool_tabs'),
    'hs_administrator': ('hs_administrator_tabs',),
    'registration': ('registration_actions', 'registration_tabs'),
    'student': ('student_actions', 'student_tabs'),
    'support_docs': ('support_docs_actions',),
    'teacher': ('teacher_tabs',),
    'term': ('term_actions', 'term_tabs'),
}


def _registry(name, actions=True, tabs=True, action_groups=()):
    """Attributes of a `<name>` registry module: `<name>_actions` (with any
    pre-declared groups, which fix the dropdown order) and `<name>_tabs`."""
    def build():
        from myce.component_registry import ActionRegistry
        from myce.component_registry.tabs import TabRegistry
        attrs = {}
        if actions:
            groups = OrderedDict((g, {'actions': OrderedDict()}) for g in action_groups)
            attrs[f'{name}_actions'] = ActionRegistry(groups)
        if tabs:
            attrs[f'{name}_tabs'] = TabRegistry()
        return attrs
    return build


# name -> (attribute factory, cis modules whose decorators fill the registry).
# Each mirrors the module Canusia/ewu ships. course and academic_year are left
# out: the host's modules wire SIS (ethos) actions cis cannot choose for it.
DEFAULTS = {
    'access_request': (_registry('access_request'), ('cis.tabs.access_request',)),
    'class_section': (_registry('class_section'), ('cis.tabs.class_section',)),
    # Apps eager-import their own index tabs from ready(); see the host module.
    'class_section_index': (_registry('class_section_index', actions=False), ()),
    'faculty_coordinator': (_registry('faculty_coordinator', actions=False),
                            ('cis.tabs.faculty_coordinator',)),
    'highschool': (_registry('highschool'), ('cis.tabs.highschool',)),
    'hs_administrator': (_registry('hs_administrator'), ('cis.tabs.hs_administrator',)),
    'registration': (_registry('registration'),
                     ('cis.tabs.registration', 'cis.actions.registration')),
    # Actions are registered by cis.views.student when the URLconf loads.
    'student': (_registry('student', action_groups=(
        'verification', 'verify_mark', 'email', 'password', 'download',
        'danger', 'bulk_only')), ('cis.tabs.student',)),
    'support_docs': (_registry('support_docs', tabs=False, action_groups=('status',)), ()),
    'teacher': (_registry('teacher'), ('cis.tabs.teacher',)),
    'term': (_registry('term'), ('cis.tabs.term',)),
}


def host_has(name):
    """Whether the host ships `myce.component_registry.<name>` (a cis
    default installed under that name does not count)."""
    dotted = f'{PACKAGE}.{name}'
    module = sys.modules.get(dotted)
    if module is not None:
        return not getattr(module, '__cis_default__', False)
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def install_defaults():
    """Register a cis default for each DEFAULTS module the host lacks, and
    return the names installed.

    Runs when the cis AppConfig is created (before any app's ready()), so a
    view imported from another app's ready() already finds the stand-in. It
    imports nothing that needs the app registry; `load_defaults` imports the
    cis tabs and actions that fill the stand-ins, from ready()."""
    try:
        if importlib.util.find_spec(PACKAGE) is None:
            return []
    except ModuleNotFoundError:  # no host `myce` package at all
        return []
    parent = importlib.import_module(PACKAGE)
    installed = []
    for name, (factory, _) in DEFAULTS.items():
        dotted = f'{PACKAGE}.{name}'
        if host_has(name) or dotted in sys.modules:
            continue
        try:
            attrs = factory()
        except ImportError:
            # The host lacks tabs.TabRegistry or ActionRegistry to build the
            # stand-in from: skip it, and let W012 name what is missing
            # rather than failing django.setup().
            continue
        module = types.ModuleType(dotted, f'cis default for {dotted} (#97).')
        # Without a spec, a later find_spec(dotted) raises ValueError (#131,
        # package-grades#11).
        module.__spec__ = importlib.machinery.ModuleSpec(dotted, None)
        module.__cis_default__ = True
        module.__dict__.update(attrs)
        sys.modules[dotted] = module
        setattr(parent, name, module)
        installed.append(name)
    return installed


def load_defaults(names):
    """Import the cis modules whose decorators fill the named stand-ins."""
    for name in names:
        for path in DEFAULTS[name][1]:
            importlib.import_module(path)


def _default_installed(name):
    module = sys.modules.get(f'{PACKAGE}.{name}')
    return getattr(module, '__cis_default__', False)


def missing_registries():
    """Host registry modules cis needs that neither the host nor cis supplies
    (including `tabs`, which no stand-in replaces, and a DEFAULTS module whose
    stand-in could not be built)."""
    return [
        name for name in ('tabs',) + REQUIRED_REGISTRIES
        if not host_has(name) and not _default_installed(name)
    ]


def missing_names():
    """(module, name) for each name cis imports that a module the host ships
    does not define, e.g. a student.py with student_actions but no
    student_tabs. A host module that fails to import is left to that error."""
    missing = []
    for name, attrs in REQUIRED_NAMES.items():
        dotted = f'{PACKAGE}.{name}' if name else PACKAGE
        if name and not host_has(name):
            continue  # missing_registries() names it
        try:
            module = importlib.import_module(dotted)
        except Exception:
            continue
        missing += [(dotted, attr) for attr in attrs if not hasattr(module, attr)]
    return missing
