// webapp/cis/staticfiles/cis/js/access_request_review.js
/* Access request review card (cis/hs_admin/access_request.html).
 *
 * Shows permissions on Approve, swaps in the matching email template, and
 * warns about placeholder mistakes as staff type. The rules mirror
 * cis.validators.validate_email_placeholders; the server re-checks and is
 * authoritative.
 */
(function ($) {
  'use strict';

  function json(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }

  var TEMPLATES = json('ar-email-templates') || {};
  var PLACEHOLDERS = json('ar-placeholders') || {};
  var MISSING_LINK = json('ar-missing-link') || '';
  var has = function (o, k) { return Object.prototype.hasOwnProperty.call(o, k); };
  var KNOWN = {};
  Object.keys(PLACEHOLDERS).forEach(function (d) {
    Object.keys(PLACEHOLDERS[d]).forEach(function (n) { KNOWN[n] = true; });
  });

  function problems(text, decision) {
    var allowed = PLACEHOLDERS[decision] || {};
    var out = [];
    text = text || '';
    if (/{%|%}/.test(text)) {
      out.push('Only plain placeholders like {{name}} are allowed here. Remove "{% ... %}".');
      text = text.replace(/{%[\s\S]*?%}/g, '');
    }
    var re = /{{([\s\S]*?)}}/g, m;
    while ((m = re.exec(text)) !== null) {
      var inner = m[1].trim();
      if (!/^\w+$/.test(inner)) {
        out.push('"' + m[0] + '" isn\'t allowed. Use a plain placeholder like {{name}}.');
      } else if (!has(allowed, inner)) {
        out.push(has(KNOWN, inner)
          ? '{{' + inner + '}} can only be used in an approval email.'
          : '{{' + inner + '}} isn\'t a placeholder. Use one of: ' +
            Object.keys(allowed).map(function (n) { return '{{' + n + '}}'; }).join(', ') + '.');
      }
    }
    var rest = text.replace(/{{[\s\S]*?}}/g, '');
    var single = rest.match(/{\s*\w+\s*}/g) || [];
    single.forEach(function (s) {
      var name = s.replace(/[{}\s]/g, '');
      out.push('Use double braces: {{' + name + '}} instead of {' + name + '}.');
    });
    rest = rest.replace(/{\s*\w+\s*}/g, '');
    if (/[{}]/.test(rest)) {
      out.push('Check the braces: there is an unclosed "{{" or a stray "}".');
    }
    return out;
  }

  function currentDecision() {
    return $('input[name="decision"]:checked').val() || null;
  }

  function render() {
    var decision = currentDecision();
    $('#ar-permissions').toggleClass('d-none', decision !== 'approve');
    $('#ar-email').toggleClass('d-none', !decision);
    $('.ar-placeholder-list').each(function () {
      $(this).toggleClass('d-none', $(this).data('decision') !== decision);
    });
    $('#ar-decide').text(decision === 'approve' ? 'Approve and send email'
                          : decision === 'deny' ? 'Deny and send email' : 'Send');
    check();
  }

  function check() {
    var decision = currentDecision();
    if (!decision) return;
    var subject = $('#id_email_subject').val();
    var message = $('#id_email_message').val();
    var list = problems(subject, decision).map(function (p) { return 'Subject: ' + p; })
      .concat(problems(message, decision).map(function (p) { return 'Message: ' + p; }));
    if (decision === 'approve' && !/{{\s*password_reset_link\s*}}/.test(message || '')) {
      list.push(MISSING_LINK);
    }
    var $box = $('#ar-placeholder-warnings');
    $box.toggleClass('d-none', list.length === 0)
        .html(list.map(function (p) { return $('<div>').text(p).html(); }).join('<br>'));
  }

  var edited = false;

  function fillTemplate(decision) {
    var t = TEMPLATES[decision];
    if (!t) return;
    $('#id_email_subject').val(t.subject);
    $('#id_email_message').val(t.message);
    edited = false;
  }

  $(function () {
    var $form = $('#ar-review-form');
    if (!$form.length) return;

    // A re-rendered form (validation errors) keeps what staff typed.
    var hasText = $('#id_email_subject').val() || $('#id_email_message').val();
    if (currentDecision() && !hasText) fillTemplate(currentDecision());
    if (hasText) edited = true;

    var previous = currentDecision();
    $form.on('change', 'input[name="decision"]', function () {
      var decision = currentDecision();
      if (previous && edited && !confirm(
          'Replace the email you edited with the ' + decision + ' template?')) {
        $('input[name="decision"][value="' + previous + '"]').prop('checked', true);
        return;
      }
      fillTemplate(decision);
      previous = decision;
      render();
    });

    $form.on('input', '#id_email_subject, #id_email_message', function () {
      edited = true;
      check();
    });

    $form.on('click', '#ar-decide', function (e) {
      var decision = currentDecision();
      var email = $('#id_email').val();
      if (!confirm((decision === 'approve' ? 'Approve' : 'Deny') +
                   ' this request and email ' + email + '?')) {
        e.preventDefault();
      }
    });

    render();
  });
})(jQuery);
