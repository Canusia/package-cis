/**
 * Form Validation and Conditional Fields
 *
 * Handles client-side validation and conditional field visibility
 * based on data-validate-* and data-depends-on attributes.
 */
(function($) {
    'use strict';

    // Validation rules
    const validators = {
        'required': function(value, param, field) {
            if (field.is(':checkbox')) {
                // A CheckboxSelectMultiple renders one <input> per choice, all
                // sharing a name, and Django copies the widget's data-validate-*
                // attrs onto every one of them. "Required" for such a group means
                // at least one box is checked — not that every box is. Validating
                // each input in isolation put a "This field is required." beside
                // every unchecked choice.
                return checkboxGroup(field).filter(':checked').length > 0;
            }

            const parts = datePartGroup(field);
            if (parts.length > 1) {
                // A SelectDateWidget renders Month/Day/Year as three <select>s
                // and Django copies the widget's data-validate-* attrs onto each
                // one. "Required" means the whole date was chosen, not that this
                // one part was — evaluating per part let a year-only selection
                // clear the error while the date was still incomplete.
                return parts.toArray().every(function (el) {
                    const partValue = $(el).val();
                    return partValue !== null && partValue !== undefined &&
                           String(partValue).trim() !== '';
                });
            }

            return value !== null && value !== undefined && value.trim() !== '';
        },

        'min-length': function(value, param, field) {
            if (!value) return true; // Don't validate empty unless required
            return value.length >= parseInt(param, 10);
        },

        'max-length': function(value, param, field) {
            if (!value) return true;
            return value.length <= parseInt(param, 10);
        },

        'pattern': function(value, param, field) {
            if (!value) return true;
            const regex = new RegExp(param);
            return regex.test(value);
        },

        'match': function(value, param, field) {
            const otherField = $('[name="' + param + '"]');
            if (!otherField.length) return true;
            return value === otherField.val();
        },

        'email': function(value, param, field) {
            if (!value) return true;
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            return emailRegex.test(value);
        },

        'numeric': function(value, param, field) {
            if (!value) return true;
            return !isNaN(value) && !isNaN(parseFloat(value));
        }
    };

    // Default error messages
    const defaultMessages = {
        'required': 'This field is required.',
        'min-length': 'Please enter at least {param} characters.',
        'max-length': 'Please enter no more than {param} characters.',
        'pattern': 'Please enter a valid format.',
        'match': 'Fields do not match.',
        'email': 'Please enter a valid email address.',
        'numeric': 'Please enter a number.'
    };

    /**
     * Return every checkbox sharing this field's name. For a lone checkbox that
     * is just the field itself; for a CheckboxSelectMultiple it is the whole
     * choice group, which must be validated and error-flagged as one unit.
     */
    function checkboxGroup(field) {
        const name = field.attr('name');
        if (!name || !field.is(':checkbox')) return field;
        const group = field.closest('form').find('input[type="checkbox"][name="' + name + '"]');
        return group.length ? group : field;
    }

    // The sub-select suffixes Django's SelectDateWidget appends to the field
    // name. Order matters: errorAnchor() puts the message after the last part
    // present, so the message lands below the whole row.
    const DATE_PART_SUFFIXES = ['_month', '_day', '_year'];

    /**
     * Return every <select> belonging to the same SelectDateWidget as this one.
     *
     * Unlike a checkbox group the parts do NOT share a name — they are
     * <base>_month / _day / _year — so they fall through the checkbox branch and
     * were being validated, flagged and messaged three times over.
     *
     * Returns an empty set unless more than one part is present, so a lone
     * select that merely happens to end in `_year` is not misidentified as a
     * date widget.
     */
    function datePartGroup(field) {
        const name = field.attr('name');
        if (!name || !field.is('select')) return $();

        const suffix = DATE_PART_SUFFIXES.find(function (candidate) {
            return name.endsWith(candidate);
        });
        if (!suffix) return $();

        const base = name.slice(0, -suffix.length);
        const selector = DATE_PART_SUFFIXES.map(function (candidate) {
            return 'select[name="' + base + candidate + '"]';
        }).join(', ');

        const parts = field.closest('form').find(selector);
        return parts.length > 1 ? parts : $();
    }

    /**
     * Every element that should carry the is-invalid flag for this field: the
     * whole checkbox group, the whole date row, or just the field.
     */
    function invalidTargets(field) {
        const parts = datePartGroup(field);
        if (parts.length > 1) return parts;
        return checkboxGroup(field);
    }

    /**
     * The element an error message should hang off. For a checkbox group that is
     * the innermost element containing the whole group — Django's own
     * <div id="id_<name>"> when the widget renders itself, or crispy's wrapper
     * around the choice divs — so one message appears for the group instead of
     * one per choice. Anything else anchors on the field itself.
     */
    function errorAnchor(field) {
        // Date widget: anchor on the LAST part so one message sits below the
        // whole Month/Day/Year row. Anchoring on the field itself inserted the
        // message between the selects and broke the row onto separate lines.
        const parts = datePartGroup(field);
        if (parts.length > 1) return parts.last();

        const group = checkboxGroup(field);
        if (group.length < 2) return field;

        const name = field.attr('name');
        const container = field.parents().filter(function() {
            return $(this).find('input[type="checkbox"][name="' + name + '"]').length === group.length;
        }).first();
        return container.length ? container : field;
    }

    /**
     * Get validation rules from a field's data attributes
     */
    function getValidationRules(field) {
        const rules = [];
        const attrs = field[0].attributes;

        for (let i = 0; i < attrs.length; i++) {
            const attr = attrs[i];
            if (attr.name.startsWith('data-validate-')) {
                const ruleName = attr.name.replace('data-validate-', '');
                if (ruleName !== 'message') {
                    rules.push({
                        name: ruleName,
                        param: attr.value
                    });
                }
            }
        }

        return rules;
    }

    /**
     * Validate a single field
     */
    function validateField(field) {
        const rules = getValidationRules(field);
        const value = field.val();
        const errors = [];

        // Skip validation if field is hidden due to depends-on
        if (field.closest('.form-group, .field-wrapper, .mb-3').is(':hidden')) {
            return { valid: true, errors: [] };
        }

        for (const rule of rules) {
            const validator = validators[rule.name];
            if (validator && !validator(value, rule.param, field)) {
                let message = field.data('validate-message') || defaultMessages[rule.name] || 'Invalid value.';
                message = message.replace('{param}', rule.param);
                errors.push(message);
                break; // Show only first error
            }
        }

        return {
            valid: errors.length === 0,
            errors: errors
        };
    }

    /**
     * Show validation error on a field
     */
    function showError(field, message) {
        clearError(field);

        const anchor = errorAnchor(field);
        invalidTargets(field).addClass('is-invalid');

        const errorDiv = $('<div class="invalid-feedback" style="display: block;"></div>').text(message);

        // Insert after the field, its input-group wrapper, or — for a checkbox
        // group — after the whole group container.
        if (anchor.is(field) && field.next('.input-group-append').length) {
            field.parent().after(errorDiv);
        } else {
            anchor.after(errorDiv);
        }
    }

    /**
     * Clear validation error from a field
     */
    function clearError(field) {
        invalidTargets(field).removeClass('is-invalid');

        const anchor = errorAnchor(field);
        if (!anchor.is(field)) {
            // Checkbox group or date row: the message sits as the anchor's sibling.
            anchor.next('.invalid-feedback').remove();
            return;
        }

        const wrapper = field.closest('.form-group, .field-wrapper, .mb-3, div').first();
        wrapper.find('.invalid-feedback').remove();
    }

    /**
     * Evaluate depends-on condition for a field
     */
    function evaluateDependsOn(field) {
        const dependsOn = field.data('depends-on');
        if (!dependsOn) return true;

        const controller = $('[name="' + dependsOn + '"]');
        if (!controller.length) return true;

        let controllerValue;
        if (controller.is(':radio')) {
            controllerValue = $('[name="' + dependsOn + '"]:checked').val() || '';
        } else if (controller.is(':checkbox')) {
            controllerValue = controller.is(':checked') ? controller.val() || 'true' : '';
        } else {
            controllerValue = controller.val() || '';
        }

        const expectedValues = (field.data('depends-value') || '').toString().split(',').map(v => v.trim());
        const negate = field.data('depends-negate') === true || field.data('depends-negate') === 'true';

        let isMatch = expectedValues.includes(controllerValue);
        if (negate) {
            isMatch = !isMatch;
        }

        return isMatch;
    }

    /**
     * Update visibility of a dependent field
     */
    function updateDependentVisibility(field) {
        const shouldShow = evaluateDependsOn(field);
        const wrapper = field.closest('.form-group, .field-wrapper, .mb-3').first();

        if (wrapper.length) {
            if (shouldShow) {
                wrapper.show();
            } else {
                wrapper.hide();
                clearError(field);
            }
        }
    }

    /**
     * Initialize conditional visibility for all fields
     */
    function initDependsOn(form) {
        const dependentFields = form.find('[data-depends-on]');

        dependentFields.each(function() {
            const field = $(this);
            const controllerName = field.data('depends-on');
            const controller = form.find('[name="' + controllerName + '"]');

            // Initial visibility
            updateDependentVisibility(field);

            // Listen for controller changes
            controller.on('change input', function() {
                updateDependentVisibility(field);
            });
        });
    }

    /**
     * Initialize form validation
     */
    function initValidation(form) {
        // Validate on blur
        form.find('input, select, textarea').on('blur', function() {
            const field = $(this);
            if (getValidationRules(field).length > 0) {
                const result = validateField(field);
                if (!result.valid) {
                    showError(field, result.errors[0]);
                } else {
                    clearError(field);
                }
            }
        });

        // Clear error on input
        form.find('input, select, textarea').on('input change', function() {
            const field = $(this);

            // A date widget's parts arrive one change at a time. Clearing on
            // the first of them made an incomplete date look satisfied, so
            // re-validate instead and keep the error until the whole date is
            // chosen. Every other control keeps the original clear-on-input
            // behaviour, with blur doing the re-validation.
            if (datePartGroup(field).length > 1 && getValidationRules(field).length > 0) {
                const result = validateField(field);
                if (result.valid) {
                    clearError(field);
                } else {
                    showError(field, result.errors[0]);
                }
                return;
            }

            clearError(field);
        });

        // Validate on submit
        form.on('submit', function(e) {
            let isValid = true;
            const firstInvalid = null;

            form.find('input, select, textarea').each(function() {
                const field = $(this);
                if (getValidationRules(field).length > 0) {
                    const result = validateField(field);
                    if (!result.valid) {
                        showError(field, result.errors[0]);
                        isValid = false;
                        if (!firstInvalid) {
                            field.focus();
                        }
                    }
                }
            });

            if (!isValid) {
                e.preventDefault();
                return false;
            }
        });
    }

    /**
     * Initialize all forms with validation
     */
    function init() {
        $('form').each(function() {
            const form = $(this);

            // Check if form has any validated fields
            if (form.find('[data-validate-required], [data-validate-pattern], [data-depends-on]').length > 0) {
                initValidation(form);
                initDependsOn(form);
            }
        });
    }

    // Auto-initialize on document ready
    $(document).ready(init);

    // Expose for manual initialization
    window.FormValidation = {
        init: init,
        initForm: function(form) {
            initValidation($(form));
            initDependsOn($(form));
        },
        validateField: validateField,
        validateForm: function(form) {
            let isValid = true;
            $(form).find('input, select, textarea').each(function() {
                const field = $(this);
                if (getValidationRules(field).length > 0) {
                    const result = validateField(field);
                    if (!result.valid) {
                        showError(field, result.errors[0]);
                        isValid = false;
                    }
                }
            });
            return isValid;
        }
    };

})(jQuery);
