"""Deliberately empty.

Re-exporting TestCase classes here makes `manage.py test cis.tests` load this
module and collect only the re-exported names: it reported 27 tests while
`manage.py test cis` reported 1,289, so a convergence check that reached for
the dotted label got a misleading pass (ewu#34).

Module-level labels are unaffected — `manage.py test cis.tests.user.User` and
`cis.tests.test_student_profile_form` both still work. Only the eight bare
class labels (`cis.tests.User`, `cis.tests.District`, …) are gone; they were an
arbitrary subset, never available for the other ~170 modules.
"""
