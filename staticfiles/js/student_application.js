$(function () {
  $("<style>")
    .prop("type", "text/css")
    .html(`
      .highlight-pulse {
          animation: highlightFade 1.5s ease-out;
          border-radius: 4px;
      }
      @keyframes highlightFade {
          0% { background-color: #fff3cd; } 
          100% { background-color: transparent; }
      }
    `)
    .appendTo("head");
  function hide($el) {
    $el.hide();
    $el.find('input, select, textarea').prop('required', false);
  }

  function reveal($el, required = true) {
    if ($el.css('display') === 'none') {
      $el.show();
      $el.removeClass('highlight-pulse');
      void $el[0].offsetWidth;
      $el.addClass('highlight-pulse');
      setTimeout(function () {
        $el.removeClass('highlight-pulse');
      }, 1500);
    }
    $el.find('input, select, textarea').prop('required', required);
  }

  function toggle_new_highschool_info() {
    let $elements = $("#div_id_new_highschool_name, #div_id_new_highschool_counselor_name, #div_id_new_highschool_counselor_email");
    if ($("#id_highschool_not_listed").is(":checked")) {
      reveal($elements, true);
      $("#id_new_highschool_name").focus();
    } else {
      hide($elements);
    }
  }

  function toggle_mailing_address_info() {
    let $mailing_divs = $("#div_id_mailing_country, #div_id_mailing_address, #div_id_mailing_address2, #div_id_mailing_city, #div_id_mailing_county, #div_id_mailing_state, #div_id_mailing_zip_code");
    let $mailing_optional_divs = $("#div_id_mailing_address2");
    if ($("#id_same_as_permanent").is(":checked")) {
      hide($mailing_divs);
    } else {
      reveal($mailing_divs, true);
      $mailing_optional_divs.find('input, select, textarea').prop('required', false);
    }
  }

  function toggle_college_attended_info() {
    let $elements = $("#div_id_college_attended_1, #div_id_college_attended_2, #div_id_college_attended_3");
    if ($("#id_other_college_credits").val() == '1') {
      reveal($elements, false);
    } else {
      hide($elements);
    }
  }



  $(document).on('change', '#id_same_as_permanent', toggle_mailing_address_info);
  $(document).on('click', '#id_highschool_not_listed', toggle_new_highschool_info);
  $(document).on('change', '#id_other_college_credits', toggle_college_attended_info);

  toggle_college_attended_info();
  toggle_new_highschool_info();
  toggle_mailing_address_info();
  // Defensive: line 2 address fields are optional and should never be forced required.
  $("#div_id_permanent_address2, #div_id_mailing_address2")
    .find('input, select, textarea')
    .prop('required', false);

  if ($.fn.multipleSelect) {
    $('#id_highschool').multipleSelect({
      filter: true,
      selectAll: false,
      single: true,
    });
  }

  $("#id_password, #id_confirm_password").css("display", 'inline-block');
  $("#hint_id_password, #hint_id_confirm_password").before('<div class="input-group-append" style="display: inline-block"><span class="input-group-text show_password" style="margin-left: -8px; padding: 10px; border-radius: 0; cursor: pointer;"><i class="far fa-eye"></i></span></div>');

  $(document).on('click', '.show_password', function () {
    let prop_value = $("#id_password").prop('type') === 'text' ? 'password' : 'text';
    $("#id_password, #id_confirm_password").prop('type', prop_value);
  });

  function validate_password_complexity() {
    const pw = $("#id_password").val();
    const $field = $("#id_password");
    let $feedback = $("#password_feedback");

    if ($feedback.length === 0) {
      $field.closest('div').after('<div id="password_feedback" style="font-size: 0.85em; margin-top: 5px;"></div>');
      $feedback = $("#password_feedback");
    }

    if (!pw) {
      $feedback.html('');
      $field[0].setCustomValidity(""); 
      return;
    }

    const hasLength = pw.length >= 12;
    const hasDigit = /\d/.test(pw);
    const hasUpper = /[A-Z]/.test(pw);
    const hasLower = /[a-z]/.test(pw);
    const hasSpecial = /[^A-Za-z0-9]/.test(pw);

    let errors = [];
    if (!hasLength) errors.push("12+ chars");
    if (!hasUpper) errors.push("1 uppercase");
    if (!hasLower) errors.push("1 lowercase");
    if (!hasDigit) errors.push("1 number");
    if (!hasSpecial) errors.push("1 special char");

    if (errors.length > 0) {
      $feedback.html('<span style="color:red">Needs: ' + errors.join(', ') + '</span>');
      $field[0].setCustomValidity("Missing requirements: " + errors.join(', ')); 
    } else {
      $feedback.html('<span style="color:green">✔ Valid format</span>');
      $field[0].setCustomValidity("");
    }
    
    validate_password_match();
  }

  function validate_password_match() {
    const pw = $("#id_password").val();
    const confirm = $("#id_confirm_password").val();
    const $field = $("#id_confirm_password");

    let $feedback = $("#confirm_feedback");
    if ($feedback.length === 0) {
      $field.closest('div').after('<div id="confirm_feedback" style="font-size: 0.85em; margin-top: 5px;"></div>');
      $feedback = $("#confirm_feedback");
    }

    if (!confirm) {
      $feedback.html('');
      $field[0].setCustomValidity(""); 
      return;
    }

    if (pw !== confirm) {
      $feedback.html('<span style="color:red">Passwords do not match</span>');
      $field[0].setCustomValidity("Passwords do not match");
    } else {
      $feedback.html('<span style="color:green">✔ Passwords match</span>');
      $field[0].setCustomValidity("");
    }
  }

  $(document).on('input', '#id_password', validate_password_complexity);
  $(document).on('input', '#id_password, #id_confirm_password', validate_password_match);

  if ($.fn.mask) {
    $('#id_ssn, #id_verify_student_ssn').mask('000-00-0000');
    $('#id_cell_phone, #id_home_phone, #id_parent_phone').mask('(000) 000-0000');
  }
});