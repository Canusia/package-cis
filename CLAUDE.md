# cis — MyCE platform core

## Package Info

- Package name: `myce_cis` · Import name: `cis` · Repo: `Canusia/package-cis`
- **Self-rooted:** the repo root IS the `cis` package. No `pkg/pkg/` nesting, and
  **no `find_spec` conditional in any host** — see README for why.
- Django app label: **`cis`**. Never set an explicit `label`; the label backs every
  `cis_*` table and all 74 applied migration rows on every deployment.

## Hard rules

- **Migration filenames are immutable.** All 74 keep their exact names. `0072` and `0073`
  differ textually between tenants but are database-equivalent (a `RunPython` already
  applied, and a choices-only `AlterField` PostgreSQL never sees). Never renumber, never
  squash.
- **`management/__init__.py` and `management/commands/__init__.py` must exist.** Django
  discovers commands by filesystem path and does not need them, but
  `setuptools.find_packages()` does — without them all 51 command modules silently vanish
  from the wheel.
- **Assets reach the wheel through `setup.py`'s `package_data`, not `MANIFEST.in`.**
  `include_package_data=True` does not work in a self-rooted layout: setuptools'
  `analyze_manifest` never matches the `'.'` `package_dir` key, so `templates/`,
  `staticfiles/` and `fixtures/` are silently dropped from every wheel. `MANIFEST.in`
  still governs the sdist. Never swap the explicit `package_data` back for
  `include_package_data=True`.
- **`setup.py` is imperative on purpose.** `find_packages()` returns bare names in a
  self-rooted layout; they are remapped onto the `cis.` prefix with
  `package_dir={'cis': '.'}`. A switch to declarative `packages = find:` would install
  `models`, `views`, `forms` as top-level packages.
- **`migrations/0056_studentregistration_mirror_fields.py` depends on
  `('ethos', '0003_resource_preferred_representation')`** and adds an M2M to
  `ethos.EthosLog`. This is an undeclared minimum-version coupling — it ships inside the
  public wheel with no corresponding `install_requires` entry — so `cis` cannot be installed
  against an `ethos` older than that migration.

## Shipping a change to `cis`

Editing files under `webapp/cis/**` on the host and merging `dev` → `staging` does **not**
ship the change. `webapp/cis` is a gitlink; `/merge-to-staging` strips gitlinks, and
production gets `cis` only from the `git+…@v0.0.1` pin in `webapp/requirements.txt`. The full
sequence to actually ship a `cis` fix:

1. Commit the change inside `webapp/cis` (it is a separate git repo).
2. Push that commit to `Canusia/package-cis`.
3. Tag a new version (e.g. `v0.0.2`).
4. Bump the pin in `webapp/requirements.txt` to the new tag.
5. `git add webapp/cis` in the host repo to move the gitlink to the new commit.
6. Merge to staging/main as usual.

**Skipping the tag-and-pin step means production silently keeps running the old version** —
the build succeeds, there is no conflict and no warning, and the fix simply never reaches
production.

## Structure

```
models/ views/ forms/ serializers/ settings/ services/ tabs/ actions/ admin/ api/
backends/ signals/ templatetags/ reports/ migrations/ management/commands/
templates/ (294 files)  staticfiles/ (77)  fixtures/ (1)  tests/ (178, shipped as `cis.tests`)
```

## Coupling

`cis` imports outward into 18 apps — `myce` (46), `future_sections` (32), `ethos` (18),
`student_transactions` (12), `student_onboarding` (12), `setting` (10),
`myce_tenant_configs` (9) and others — while `future_sections` imports `cis` 150 times in
return. This is mutual coupling by design; it is documented as host requirements rather
than declared as dependencies.

`grades` is the exception, and the pattern to copy when an app should be optional: as of
v0.0.4 `cis` imports it exactly zero times. All grade logic moved into the `grades` package,
and the handful of cis features that need a grade fact call `cis/integrations/grades.py`,
which detects the app with `find_spec` once at import and returns safe defaults when it is
missing. Never reintroduce a direct `from grades …` import into `cis`.

## Tenant seam

Per-tenant behaviour resolves through `cis.services.tenant_services.get_tenant_service()`,
backed by each tenant's in-tree `myce_tenant_configs`. Eleven seams exist today
(`sis_importer`, `registration_form`, `recommendation_form`, `ferpa_form`,
`verify_email_form`, `highschool_types`, `bulk_enroller`, `onboarding_steps`,
`ethos_identity`, `registration`, …). The form seams are re-exported by the PEP 562
`__getattr__` shim at the bottom of `forms/student.py` — adding one means adding an entry to
`_TENANT_FORMS` there **and** shipping the module in every tenant, or that tenant breaks at
first use. See README → "Required tenant service modules".

Those eleven are **required** modules — a tenant missing one breaks at first use.
`services/tenant_services.get_tenant_override(module, attr)` is the **opt-in**
form: `cis` keeps a working default and a tenant overrides only if it defines the
named function. As of v0.0.18 the `registration` module carries five such hooks —
`needs_recommendation`, `has_recommendation`, `get_pending_recommendations`,
`student_needs_recommendation` and `counselor_notification_groups` — so a tenant
that ships none of them is unaffected. v0.0.20 adds a second opt-in module,
`faculty_scope`, with `visible_teachers(user, academic_year=None)`. Prefer this
form for behaviour that has a sensible platform default; reserve the
required-module form for things `cis` genuinely cannot supply.

One trap when writing an opt-in module: re-export the **default**, not the seam
wrapper. `faculty_scope` exposes `default_visible_teachers` for exactly this —
a tenant re-exporting `visible_teachers` would make the seam resolve the
override to the wrapper itself and recurse until the stack blew. The wrapper
guards with an `is not` check, so the wrong shape is merely redundant, but the
default is the name to re-export.

The 29 `reports/`, 22 `services/importers/` schemas and four ewu-flavoured modules
(`tabs/faculty_coordinator.py`, `settings/student_profile.py`,
`forms/application_validators.py`, `forms/application_form.py`) are **not** behind the
seam yet — deferred to v0.0.2+, driven by what lsco/sccc convergence surfaces.
