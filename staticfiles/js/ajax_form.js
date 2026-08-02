/**
 * AJAX Form Handler
 *
 * Handles form submissions via AJAX with:
 * - UI blocking during submission
 * - Inline validation error display
 * - Success/error alerts via sweetalert
 * - File upload support via FormData
 *
 * Usage:
 *   <form class="frm_ajax" action="/api/endpoint/" method="post">
 *       {% csrf_token %}
 *       {{ form|crispy }}
 *       <button type="submit">Save</button>
 *   </form>
 *
 *   For file uploads, add enctype:
 *   <form class="frm_ajax" action="/api/endpoint/" method="post" enctype="multipart/form-data">
 *
 * Expected server responses:
 *   Success: {"message": "...", "status": "success", "action": "reload"}
 *            {"message": "...", "status": "success", "action": "refresh_table", "table_id": "tbl_name"}
 *   Error:   {"errors": {"field": [{"message": "..."}]}, "message": "..."}
 */
$(document).on('submit', 'form.frm_ajax', function(event) {
    event.preventDefault();

    var $form = $(this);
    var $container = $form.closest('.card-body').length
        ? $form.closest('.card-body')
        : $form.parent();

    $container.block();

    // Clear previous validation errors (scoped to this form only)
    $form.find('.is-invalid').removeClass('is-invalid');
    $form.find('.invalid-feedback').remove();

    // Check if form has file uploads
    var hasFiles = $form.attr('enctype') === 'multipart/form-data' ||
                   $form.find('input[type="file"]').length > 0;

    // Build AJAX options
    var ajaxOptions = {
        url: $form.attr('action'),
        type: 'POST',
        success: function(response) {
            $container.unblock();

            // Reset form if successful
            if (hasFiles) {
                $form[0].reset();
            }

            swal({
                title: 'Success',
                text: response.message,
                icon: 'success'
            }).then(function() {
                if (response.action === 'reload') {
                    location.reload();
                } else if (response.action === 'redirect' && response.redirect_url) {
                    window.location.href = response.redirect_url;
                } else if (response.action === 'refresh_table' && response.table_id) {
                    // Refresh a specific DataTable without page reload
                    var table = $('#' + response.table_id).DataTable();
                    if (table) {
                        table.ajax.reload();
                    }
                }
            });
        },
        error: function(xhr) {
            $container.unblock();

            var response = xhr.responseJSON || {};
            var errors = response.errors || {};
            var $firstField = null;

            // Display inline validation errors
            for (var fieldName in errors) {
                var $field = $form.find('[name="' + fieldName + '"]');
                if ($field.length) {
                    $field.addClass('is-invalid');

                    // Handle both {"message": "..."} and plain string formats
                    var errorList = errors[fieldName];
                    var msg = '';
                    if (Array.isArray(errorList)) {
                        msg = errorList[0].message || errorList[0];
                    } else {
                        msg = errorList;
                    }

                    $field.after('<div class="invalid-feedback d-block">' + msg + '</div>');

                    if (!$firstField) {
                        $firstField = $field;
                    }
                }
            }

            // Focus first field with error
            if ($firstField) {
                $firstField.focus();
            }

            // Show error alert
            swal({
                title: 'Error',
                text: response.message || 'Please fix the errors and try again',
                icon: 'warning'
            });
        }
    };

    // Use FormData for file uploads, serialize() for regular forms
    if (hasFiles) {
        ajaxOptions.data = new FormData($form[0]);
        ajaxOptions.processData = false;
        ajaxOptions.contentType = false;
    } else {
        ajaxOptions.data = $form.serialize();
    }

    $.ajax(ajaxOptions);
});
