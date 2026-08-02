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
                return field.is(':checked');
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

        const wrapper = field.closest('.form-group, .field-wrapper, .mb-3, div').first();
        field.addClass('is-invalid');

        const errorDiv = $('<div class="invalid-feedback" style="display: block;"></div>').text(message);

        // Insert after the field or its wrapper
        if (field.next('.input-group-append').length) {
            field.parent().after(errorDiv);
        } else {
            field.after(errorDiv);
        }
    }

    /**
     * Clear validation error from a field
     */
    function clearError(field) {
        field.removeClass('is-invalid');
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
            clearError($(this));
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
