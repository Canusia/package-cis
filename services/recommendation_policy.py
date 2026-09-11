"""The one place that decides whether a registration needs a recommendation.

The rule has two implementations that must agree: exact list membership in
Python (``StudentRegistration.needs_recommendation``,
``get_pending_recommendations``, ``Student.needs_recommendation``) and a
``Q`` builder for the ORM (``recommendation_required_q``, behind the counselor
chase-up email and the CE ``missing_recommendation`` report). They answer the
same question on different surfaces, so a student can appear in the high-school
Pending Recommendation tab while the Classes table beside it says "No".

Both now read the gate from here. Changing the policy means changing this
module, not five call sites.
"""


def grade_gate_enabled():
    """Whether the grade-level match is part of the rule.

    Imported inside the function rather than at module level: the setting
    reaches ``cis.models.settings``, and resolving that while a ``cis`` model
    module is still importing risks AppRegistryNotReady — the same reason
    ``_tenant_registration_override`` defers its import.
    """
    from cis.settings.recommendation_policy import recommendation_policy

    return recommendation_policy.grade_match_required()


def registration_requires_recommendation(grade_level, eligibility,
                                         gate_enabled=None):
    """Whether `eligibility` requires a recommendation from a `grade_level` student.

    The Python half of the rule. ``eligibility`` is a MultiSelectField value —
    a list of grade codes where a ``*`` suffix marks "needs a recommendation".

    Gate on:  the student's own grade must carry the asterisk.
    Gate off: any asterisk on the course is enough, whatever the student's
              grade. A course carrying no asterisk still requires nothing, so
              the per-course flag CE admins set keeps its meaning.

    ``gate_enabled`` lets a caller looping over rows resolve the setting once
    and pass it in. Reading it per row costs a ``Setting`` query per row, which
    is the N+1 that `select_related` in ``get_pending_recommendations`` exists
    to avoid — two tests there assert the query count stays flat as rows grow.
    Omit it for a single row and it resolves itself.
    """
    eligibility = eligibility or []

    if gate_enabled is None:
        gate_enabled = grade_gate_enabled()

    if not gate_enabled:
        return any(str(value).endswith('*') for value in eligibility)

    return f'{grade_level}*' in eligibility
