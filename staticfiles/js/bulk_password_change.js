
$(function () {

  var form = $('#frm_bulk_password')

  function toggleEmail(show) {
    if(show) {
      $("#div_id_email_subject, #div_id_email_message").show()
    } else {
      $("#div_id_email_subject, #div_id_email_message").hide()
    }
  }

  toggleEmail(false)

  $(document).on('change', '#id_send_email', function() {
    if($(this).val() == '1')
      toggleEmail(true)
    else
      toggleEmail(false)
  })
});