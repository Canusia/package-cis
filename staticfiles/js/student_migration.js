
jQuery(document).ready(function ($) {

  $(document).on('keyup', '#id_destination_student_id', function() {

    
    let ajaxurl = "/ce/student/details";
    let data = {
      "studentid": $(this).val()
    }

    $.get(ajaxurl, data, function (response) {
      $("#migrate_student_info").html(response.message)
    });
  })
});
