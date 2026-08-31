/* HS administrator detail page: delete + optional role revocation.
 *
 * The delete removes the HSAdministrator record only. When the account is left
 * with no high school roles, staff are offered the role revocation; declining
 * is fine — the account then shows up on the Dangling Accounts tab of
 * /ce/highschool_admins/, where the same action is available later.
 */
jQuery(function ($) {
  'use strict';

  function csrfToken() {
    // Prefer the token exposed by logged-base.html via Django's csrf_token
    // context variable -- it is the token value itself, independent of
    // whatever CSRF_COOKIE_NAME this tenant configures (e.g. ewu_csrftoken).
    if (window.CSRF_TOKEN) return window.CSRF_TOKEN;

    // Fallback for pages that don't extend logged-base.html: scan cookies.
    // Try the Django default name first, then tolerate any tenant-prefixed
    // cookie name (ewu_csrftoken, nnu_csrftoken, ...) by matching the suffix.
    var parts = document.cookie ? document.cookie.split(';') : [];
    var suffixMatch = null;
    for (var i = 0; i < parts.length; i++) {
      var c = parts[i].trim();
      var eq = c.indexOf('=');
      if (eq === -1) continue;
      var cookieName = c.substring(0, eq);
      if (cookieName === 'csrftoken') {
        return decodeURIComponent(c.substring(eq + 1));
      }
      if (suffixMatch === null && cookieName.length > 'csrftoken'.length &&
          cookieName.slice(-'csrftoken'.length) === 'csrftoken') {
        suffixMatch = decodeURIComponent(c.substring(eq + 1));
      }
    }
    return suffixMatch || '';
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

  function finishDelete(response) {
    if (response.status !== 'success') return;

    if (window.frameElement !== null) {
      window.parent.closeModal();
    } else {
      window.location = response.redirect;
    }
  }

  function offerRoleRevocation(response) {
    var prompt = response.admin_name + ' holds no high school roles. ' +
      'Remove their high school administrator access?';

    if (response.other_roles && response.other_roles.length) {
      prompt += ' They will keep their ' + response.other_roles.join(', ') + ' access.';
    }

    swal({
      title: 'Remove administrator access?',
      text: prompt,
      icon: 'warning',
      buttons: ['Keep access', 'Remove access'],
    }).then(function (confirmed) {
      if (!confirmed) {
        finishDelete(response);
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
          }).then(function () {
            finishDelete(response);
          });
        },
        error: function (xhr) {
          $.unblockUI();
          swal('Error', ajaxErrorMessage(xhr), 'error').then(function () {
            finishDelete(response);
          });
        },
      });
    });
  }

  $('a.hs-admin-delete').on('click', function (event) {
    event.preventDefault();

    if (!confirm('Are you sure you want to delete this administrator record? ' +
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
          if (response.status === 'success' && response.hs_admin_role_revocable) {
            offerRoleRevocation(response);
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
