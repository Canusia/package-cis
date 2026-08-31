/* Student detail page: delete + optional role revocation.
 *
 * The delete removes the Student record only. When the account is left
 * with no Student record, staff are offered the role revocation; declining
 * is fine — the account then shows up on the Dangling Accounts tab of
 * /ce/students/, where the same action is available later.
 */
jQuery(function ($) {
  'use strict';

  function csrfToken() {
    var name = 'csrftoken=';
    var parts = document.cookie ? document.cookie.split(';') : [];
    for (var i = 0; i < parts.length; i++) {
      var c = parts[i].trim();
      if (c.indexOf(name) === 0) return decodeURIComponent(c.substring(name.length));
    }
    return '';
  }

  // 403s and 500s return HTML, not JSON, so responseJSON is undefined.
  function ajaxErrorMessage(xhr) {
    if (xhr.responseJSON && xhr.responseJSON.message) return xhr.responseJSON.message;
    if (xhr.status === 403) {
      return 'Your session may have expired, or you do not have permission. ' +
             'Please reload the page and try again.';
    }
    return 'Something went wrong (HTTP ' + xhr.status + '). Please try again.';
  }

  // Shared with the plain a.student-delete handler below and with
  // onRecordDeleted() in cis/students/detail.html, which drives the same
  // prompt from the Actions-dropdown registry-action response.
  function offerRoleRevocation(response, onDone) {
    var prompt = response.student_name + ' holds no Student record. ' +
      'Remove their student access?';

    if (response.other_roles && response.other_roles.length) {
      prompt += ' They will keep their ' + response.other_roles.join(', ') + ' access.';
    }

    swal({
      title: 'Remove student access?',
      text: prompt,
      icon: 'warning',
      buttons: ['Keep access', 'Remove access'],
    }).then(function (confirmed) {
      if (!confirmed) {
        onDone();
        return;
      }

      $.blockUI();
      $.ajax({
        type: 'POST',
        url: response.revoke_url,
        headers: { 'X-CSRFToken': csrfToken() },
        success: function (revokeResponse) {
          $.unblockUI();
          swal({
            title: revokeResponse.status === 'success' ? 'Done' : 'Not removed',
            text: revokeResponse.message,
            icon: revokeResponse.status,
          }).then(onDone);
        },
        error: function (xhr) {
          $.unblockUI();
          swal('Error', ajaxErrorMessage(xhr), 'error').then(onDone);
        },
      });
    });
  }

  window.offerStudentRoleRevocation = offerRoleRevocation;

  function finishDelete(response) {
    if (response.status !== 'success') return;

    if (window.frameElement !== null) {
      window.parent.closeModal();
    } else {
      window.location = response.redirect;
    }
  }

  $('a.student-delete').on('click', function (event) {
    event.preventDefault();

    if (!confirm('Are you sure you want to delete this student record? ' +
                 'The user account is not deleted.'))
      return;

    var url = $(this).attr('data-url');

    $.blockUI();
    $.ajax({
      type: 'POST',
      url: url,
      headers: { 'X-CSRFToken': csrfToken() },
      success: function (response) {
        $.unblockUI();
        swal({
          title: 'Success',
          text: response.message,
          icon: response.status,
        }).then(function () {
          if (response.status === 'success' && response.student_role_revocable) {
            offerRoleRevocation(response, function () { finishDelete(response); });
          } else {
            finishDelete(response);
          }
        });
      },
      error: function (xhr) {
        $.unblockUI();
        swal('Error', ajaxErrorMessage(xhr), 'error');
      },
    });
  });
});
