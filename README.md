# MyCE — core platform app (`cis`)

The MyCE concurrent-enrollment platform core: students, registrations, high schools,
instructors, courses, sections, terms, campus scoping, settings and the CE admin portal.

- **Package name:** `myce_cis`
- **Import name:** `cis`
- **Repo:** <https://github.com/Canusia/package-cis>

## Install

```
git+https://github.com/Canusia/package-cis.git@<tag>
```

Pin a specific tag — see the repository's tags for the current release. Never
track `main`: the host records which commit it was built against in its
`webapp/cis` gitlink, and an unpinned host would drift from it.

Development uses a git submodule at `webapp/cis`.

## Self-rooted layout

The repository root **is** the `cis` package — `models/`, `views/`, `migrations/` and the
rest sit at top level beside `pyproject.toml`. Mounted as a submodule it imports as `cis`;
pip-installed it imports as `cis`.

This deliberately differs from the other Canusia packages (`drop_wd`, `docrepo`,
`highschool_admin`, …), which use a 2-deep `pkg/pkg/` layout selected by
`importlib.util.find_spec`. That pattern cannot work here: 187 distinct `cis.*` module
paths are imported 1,374 times across 28 apps, and the packages shipped to every tenant
import `cis` too (`highschool_admin` 191 times, `future_sections` 150, `instructor_app`
126, `class_visit` 119). Those imports are hardcoded inside third-party packages where
`cis` is always flat, so they cannot be `find_spec`-switched.

**There is therefore no `find_spec` conditional for `cis` in any host.**

## Host wiring

`INSTALLED_APPS` keeps `'cis.apps.CisConfig'` and the URLconf keeps `include('cis.urls')` —
both unchanged, because the import name never changes. Only static files move:

```python
os.path.join(get_package_path("cis"), 'staticfiles')
```

which resolves to `webapp/cis/staticfiles` in dev and `site-packages/cis/staticfiles` in
production. `APP_DIRS=True` finds `cis/templates` in both layouts.

## Host requirements

This is a platform core, not a standalone library. A host must provide the `myce` Django
project package (settings, `component_registry`), the per-tenant `myce_tenant_configs` app,
and the sibling apps `future_sections`, `ethos`, `student_transactions`,
`student_onboarding`, `setting`, `announcement`, `class_visit`, `highschool_admin`,
`alerts`, `two_step`, `support_ticket`, `pd_event`, `instructor_app`, `drop_wd`,
`instructor` and `degree_pathway`.

`grades` is **optional** as of v0.0.4. `cis` no longer imports it; the three places that
need a grade fact — the sections-list grade stats, the class-export grade columns and
`StudentRegistration.submitted_grade` — go through `cis/integrations/grades.py`, which
returns safe defaults when the app is absent. `cis.utils.grades_page_header_for_instructor`,
`is_submit_grades_open` and `can_view_grades`, and `Student.generate_unofficial_transcript`,
are delegations kept for host callers.

Do not add `from grades …` anywhere else in `cis`; `cis/integrations/grades.py` is the only
sanctioned seam.

None of them are declared in `install_requires`. That matches Canusia convention and avoids
a circular pin with `future_sections`, which imports `cis` 150 times.

### Required tenant service modules

Some forms live in the tenant app and are re-exported by a `cis` shim. A host **must** ship
each of these under `myce_tenant_configs/services/`, or the corresponding import raises at
first use:

| Module | Must export | Used by |
|---|---|---|
| `verify_email_form.py` | `StudentVerifyEmailForm` | student signup at `/student/start_request/`, and `seed_demo_students` |
| `ferpa_form.py` | `StudentFerpaForm` | student FERPA page, `StudentFerpa.asHTML` |
| `recommendation_form.py` | `StudentRecommendationForm` | HS-admin student recommendation |
| `registration_form.py` | `EditStudentRegistration` | CE registration detail/edit |
| `student_profile_form.py` | `StudentProfileForm`, `EDITABLE_FIELDS` | student profile, CE student edit, importer |

`verify_email_form.py` is **new in v0.0.3** — a tenant upgrading from v0.0.2 must add it
before deploying, or `/student/start_request/` fails to resolve the form.

## Tests

The 182 test modules live in the repo but are excluded from the distribution. Run them
against a tenant's submodule checkout:

```bash
docker exec -w /app/webapp django_web_ewu python manage.py test cis
```
