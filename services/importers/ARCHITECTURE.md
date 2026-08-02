# Importers Architecture

This document describes the design and data flow of the CSV import system in
`cis/services/importers/`.

---

## Overview

The importer system provides a structured way to ingest CSV data into MyCE
Django models. Each importable entity follows a two-file convention:

| File | Purpose |
|---|---|
| `<entity>_schema.py` | Pydantic model defining CSV columns, types, and validation rules |
| `<entity>_importer.py` | Import engine that orchestrates validation, FK resolution, and persistence |

Supporting modules:

| File | Purpose |
|---|---|
| `validation.py` | Shared `ValidationError` and `ImportResult` dataclasses |
| `__init__.py` | Re-exports all schemas and importers for convenient access |

### Current Entities

| Entity | Schema class | Importer class | Match key |
|---|---|---|---|
| ClassSection | `ClassSectionRow` | `ClassSectionImporter` | `(term, class_number)` |
| HighSchool | `HighSchoolRow` | `HighSchoolImporter` | `code` |
| HS Member | `HSMemberRow` | `HSMemberImporter` | `email` |
| Academic Year | `AcademicYearRow` | `AcademicYearImporter` | `name` |
| Term | `TermRow` | `TermImporter` | `code` |
| Cohort | `CohortRow` | `CohortImporter` | `designator` |
| Course | `CourseRow` | `CourseImporter` | `name` |

---

## Pydantic Schemas (`*_schema.py`)

Each schema is a `pydantic.BaseModel` subclass that serves as the **single
source of truth** for its entity's import contract. The schema defines:

### Field declarations

```python
name: str = Field(
    min_length=1,
    description="Term name",
    json_schema_extra={"db_field": "term", "is_lookup": True}
)
```

- **Type + required/optional** — drives pydantic validation and coercion.
- **`description`** — displayed in the CSV upload UI as column help text.
- **`json_schema_extra`** metadata:
  - `db_field` — the Django model field this CSV column maps to.
  - `is_lookup` (optional) — when `True`, the value requires FK resolution
    (e.g. looking up a `Term` by `code`) rather than direct assignment.

### Validators

Schemas use `@field_validator` and `@model_validator` decorators for rules
like:

- **Type coercion** — empty strings to `None`, empty strings to default
  values.
- **Format checks** — `course_name` must contain a space (`"BIO 101"`),
  `cancel_flag` must be `Y` or `N`.
- **Cross-field rules** — `start_date` must be before `end_date`
  (model validator).
- **Normalization** — lowercasing emails, collapsing double spaces, replacing
  HTML entity dashes.

### Utility class methods

Every schema provides these introspection methods (used by importers and the
web UI):

| Method | Returns | Used by |
|---|---|---|
| `csv_headers()` | All CSV column names in order | CSV template download, header validation |
| `required_headers()` | Only required column names | UI display, header validation |
| `field_definitions()` | List of `{name, description, required, type}` dicts | Upload form field table |
| `db_field_mapping()` | `{csv_column: db_field}` for direct fields | `_build_db_fields()` in importers |
| `lookup_fields()` | `{csv_column: db_field}` for FK lookup fields | Importer FK resolution |

### Schema reuse outside CSV import

Schemas are also used by the REST API layer. For example,
`cis/api/class_section.py` validates incoming JSON POST bodies against
`ClassSectionRow` before resolving FKs and creating `ClassSection` records.
A small mapping layer (`_api_payload_to_schema_dict`) translates API field
names to schema field names where they differ.

---

## Importers (`*_importer.py`)

Each importer class orchestrates the full CSV-to-database pipeline. There are
two tiers of complexity:

### Simple importers

`AcademicYearImporter`, `TermImporter`, `CohortImporter`, `CourseImporter`
process rows one at a time. Their flow:

```
CSV row (dict)
  -> _validate_and_clean_row()  [pydantic schema]
  -> _get_related_objects()     [FK resolution]
  -> get_or_create / update     [Django ORM]
  -> ImportResult
```

### Bulk importers

`ClassSectionImporter`, `HighSchoolImporter`, `HSMemberImporter` support
configurable bulk operations for performance. Their flow has distinct phases:

```
Phase 1: Validate all rows
  CSV rows -> _validate_and_clean_row() for each -> split into valid/invalid

Phase 2: Process valid rows in batches
  For each batch:
    2a. Prepare:    _get_related_objects() for FK resolution
    2b. Fetch:      bulk query existing records by match key
    2c. Classify:   separate creates from updates
    2d. Execute:    bulk_create() new records, bulk_update() existing ones
    2e. Results:    build ImportResult list

Final: _build_summary() -> {status, records, summary}
```

### Configuration options

Bulk importers accept these constructor parameters:

| Parameter | Default | Description |
|---|---|---|
| `use_bulk_operations` | `True` | Use `bulk_create`/`bulk_update` vs individual `.save()` |
| `batch_size` | `500` | Records per bulk operation batch |
| `use_transactions` | `'none'` | Transaction strategy (see below) |

**Transaction strategies:**

| Value | Behavior |
|---|---|
| `'none'` | No wrapping — fastest, imports all good rows even if some fail |
| `'per_row'` | Each row in its own `transaction.atomic()` |
| `'per_batch'` | Each batch in its own `transaction.atomic()` |
| `'all'` | Entire import in one `transaction.atomic()` (all-or-nothing) |

### Error handling

- **Validation errors** are collected per-row and returned in the result set
  without aborting other rows.
- **FK resolution failures** raise exceptions caught at the row/batch level.
- **Bulk operation failures** fall back to individual `.save()` calls when
  not using per-batch transactions.
- Every row gets a `RESULT` key appended to its dict (`'Success'` or an
  error message) for display in the UI results table.

---

## Shared Validation Types (`validation.py`)

```python
@dataclass
class ValidationError:
    field: str       # CSV column name
    message: str     # Human-readable error

@dataclass
class ImportResult:
    success: bool
    row_data: Dict                              # Original CSV row + RESULT key
    error_message: Optional[str]
    validation_errors: List[ValidationError]    # Per-field errors
```

These are used consistently across all importers and are re-exported from
`__init__.py`.

---

## Data Flow Diagram

```
                          CSV Upload (Web UI)          REST API POST
                                |                           |
                                v                           v
                         DictReader rows              JSON payload
                                |                           |
                                v                           v
                    +-------------------+      +------------------------+
                    | Pydantic Schema   |      | Pydantic Schema        |
                    | (model_validate)  |      | (model_validate with   |
                    |                   |      |  field name remapping) |
                    +-------------------+      +------------------------+
                                |                           |
                         validated row               validated row
                                |                           |
                                v                           v
                    +-------------------+      +------------------------+
                    | Importer          |      | DRF Serializer         |
                    | (_get_related_    |      | (validate → FK         |
                    |  objects)         |      |  resolution)           |
                    +-------------------+      +------------------------+
                                |                           |
                         FK objects                  FK objects
                                |                           |
                                v                           v
                    +-------------------+      +------------------------+
                    | bulk_create /     |      | ClassSection           |
                    | bulk_update /     |      |   .update_or_add()     |
                    | individual .save  |      |                        |
                    +-------------------+      +------------------------+
                                |                           |
                                v                           v
                         ImportResult               DRF Response (201)
```

---

## Adding a New Importer

1. **Create `<entity>_schema.py`** — define a `pydantic.BaseModel` with:
   - Field declarations (types, `Field(...)`, `json_schema_extra` with
     `db_field` and optionally `is_lookup`)
   - Validators for type coercion and business rules
   - The standard utility class methods (`csv_headers`, `required_headers`,
     `field_definitions`, `db_field_mapping`, `lookup_fields`)

2. **Create `<entity>_importer.py`** — implement the importer class with:
   - `process_csv(dictReader)` as the entry point
   - `_validate_and_clean_row()` delegating to the pydantic schema
   - `_get_related_objects()` for FK resolution
   - Create/update logic (bulk or individual depending on needs)

3. **Register in `__init__.py`** — add imports and `__all__` entries.

4. **Wire up the view** — add a CSV upload view (typically in
   `cis/views/`) that reads the uploaded file, creates a `DictReader`,
   calls `importer.process_csv(reader)`, and renders the results.

---

## File Inventory

```
cis/services/importers/
    __init__.py                    # Re-exports all schemas and importers
    validation.py                  # Shared ValidationError, ImportResult
    ARCHITECTURE.md                # This document
    class_section_schema.py        # ClassSectionRow pydantic schema
    class_section_importer.py      # ClassSectionImporter (bulk)
    highschool_schema.py           # HighSchoolRow pydantic schema
    highschool_importer.py         # HighSchoolImporter (bulk)
    hs_member_schema.py            # HSMemberRow pydantic schema
    hs_member_importer.py          # HSMemberImporter (bulk)
    academic_year_schema.py        # AcademicYearRow pydantic schema
    academic_year_importer.py      # AcademicYearImporter (simple)
    term_schema.py                 # TermRow pydantic schema
    term_importer.py               # TermImporter (simple)
    cohort_schema.py               # CohortRow pydantic schema
    cohort_importer.py             # CohortImporter (simple)
    course_schema.py               # CourseRow pydantic schema
    course_importer.py             # CourseImporter (simple)
```
