jQuery(document).ready(function ($) {
  $("a.delete-record").on("click", function () {
      if (!confirm("Are you sure you want to permanently delete this record?"))
          return;

      $.blockUI();
      let url = $(this).attr('data-url')
      
      $.ajax({
          type: 'GET',
          url: url,
          success: function (response) {
              $.unblockUI();
              swal(
                  "",
                  response.message,
                  response.status
              )
              if (response.status == 'success') {
                  window.parent.closeModal();
              }
          },
          error: function (xhr, ajaxOptions, thrownError) {

              $.unblockUI();
              response = xhr.responseJSON
              swal(
                  "",
                  response.message,
                  response.status
              )
          }
      });
  });
});