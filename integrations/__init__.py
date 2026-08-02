"""Optional-app integration seams for ``cis``.

Each module here wraps exactly one app that ``cis`` may talk to but must not
depend on. Nothing in this package may be imported at ``cis`` import time in a
way that makes the wrapped app mandatory.
"""
