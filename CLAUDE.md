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

## Structure

```
models/ views/ forms/ serializers/ settings/ services/ tabs/ actions/ admin/ api/
backends/ signals/ templatetags/ reports/ migrations/ management/commands/
templates/ (294 files)  staticfiles/ (77)  fixtures/ (1)  tests/ (182, not shipped)
```

## Coupling

`cis` imports outward into 19 apps — `myce` (46), `future_sections` (32), `ethos` (18),
`grades` (14), `student_transactions` (12), `student_onboarding` (12), `setting` (10),
`myce_tenant_configs` (9) and others — while `future_sections` imports `cis` 150 times in
return. This is mutual coupling by design; it is documented as host requirements rather
than declared as dependencies.

## Tenant seam

Per-tenant behaviour resolves through `cis.services.tenant_services.get_tenant_service()`,
backed by each tenant's in-tree `myce_tenant_configs`. Ten seams exist today
(`sis_importer`, `registration_form`, `recommendation_form`, `ferpa_form`,
`highschool_types`, `bulk_enroller`, `onboarding_steps`, `ethos_identity`, `registration`,
…). The 29 `reports/`, 22 `services/importers/` schemas and four ewu-flavoured modules
(`tabs/faculty_coordinator.py`, `settings/student_profile.py`,
`forms/application_validators.py`, `forms/application_form.py`) are **not** behind the
seam yet — deferred to v0.0.2+, driven by what lsco/sccc convergence surfaces.
