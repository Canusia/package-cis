/* Student detail page: role-revocation prompt.
 *
 * Prompt-only module: the delete itself runs through the Actions-dropdown
 * registry action (delete_student in views/student.py), which is already
 * POST-only via the record-action dispatcher. This file exists to offer the
 * follow-up "remove student access?" prompt once that delete leaves the
 * account with no Student record; declining is fine — the account then
 * shows up on the Dangling Accounts tab of /ce/students/, where the same
 * action is available later. It exposes window.offerStudentRoleRevocation,
 * called from onRecordDeleted() in cis/students/detail.html.
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
});
