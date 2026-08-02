function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
          const cookie = cookies[i].trim();
          if (cookie.substring(0, name.length + 1) === (name + '=')) {
              cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
              break;
          }
      }
  }
  return cookieValue;
}

function formatAmount(amount) {
  return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
  }).format(amount)
}

window.closeAddNewModal = function () {
    $('#modal-add_new').modal('hide');
};

window.closeBulkActionModal = function () {
  $('#modal-bulk_actions').modal('hide');
};

window.closeModal = function () {
  $('.modal').modal('hide');
};

jQuery(document).ready(function ($) {

  if(window.frameElement !== null) {
    $(".navbar, #accordionSidebar, footer").hide()
  }
  
  $("form:not(.filter) :input:visible:enabled:first").focus();
    
  $('.datetimeinput').mask('00/00/0000 00:00');
  $('.dateinput:not([type=date])').mask('00/00/0000');

  $('#id_date_of_birth').mask('00/00/0000');
  $('#id_ssn').mask('000-00-0000');
  $('.dateinput:not([type=date])').datepicker()

  $("#sidebarToggle").on("click", function () {
    let toggled = $('body ul.sidebar').hasClass('toggled')
    Cookies.set('mycis_sidebar_toggled', toggled);
  });


  if($('#sidebarToggleTop').css('display') == 'block') {
    $("body ul.sidebar").addClass("toggled")

    $('.container-fluid').css('padding-left', '10px')
    $('.container-fluid').css('padding-right', '10px')

    Cookies.set('is_mobile', '1');
  } else {
    Cookies.set('is_mobile', '2');
  }

  window.closeModal = function () {
      $('#details').modal('hide');
  };

  jQuery(function ($) {
      $(function () {
        $('[data-toggle="popover"]').popover({ html: true, trigger: 'hover' })
      })
      
      var updater = "";
      var modal = "";

      $(document).ready(function () {
        // show active tab on reload
        if (location.hash !== '') $('.nav-tabs a[href="' + location.hash + '"]').tab('show');

        // remember the hash in the URL without jumping
        $('a[data-toggle="tab"]').on('shown.bs.tab', function (e) {
          if (history.pushState) {
            history.pushState(null, null, '#' + $(e.target).attr('href').substr(1));
          } else {
            location.hash = '#' + $(e.target).attr('href').substr(1);
          }
        });
      });

      $(document).on("submit", "#modal-add_new form", function (event) {
        let ajaxurl = "/ce/add_new_ajax/"

        if ($("input[name='action']").val() == "not-teaching-section")
          return;

        if ($("input[name='action']").val() == "add_new_teacher")
          return;

        if ($("input[name='action']").val() == "teaching-section")
          return;

        var form = this
        var formData = new FormData(this)

        $.ajax({
          type: "POST",
          url: ajaxurl,
          data: formData, // $(".modal-content form").serialize(),
          processData: false,
          contentType: false,
          success: function (response) {
            if (response.status == 'error') {
              $(".modal-content .form_status").html("<p class='alert alert-danger'>" + response.message + "</p>");
            } else {
              $(".modal-content .form_status").html("<p class='alert alert-success'>" + response.message + "</p>");

              if (response.action == 'reload') {
                $("#" + modal).modal('hide');
                location.reload();
              } else {
                //add new record to list
                $("#" + updater).append("<option selected value='" + response.new_record_id + "'>" + response.new_record_name + "</option>")
                $("#" + modal).modal('hide');
              }
            }
          },
          error: function (response) {
            alert('There was an error submitting the form');
          }
        });
        event.preventDefault();
      });

      var clipboard = new ClipboardJS('.copy-clipboard');
      clipboard.on('success', function(e) {
          e.clearSelection();
          $('.copy-clipboard').css('color', 'green').append('<small>&nbsp;Copied</small>')
      });

      $(document).on("click", ".ajax-pwd_reset_link", function () {
        updater = $(this).attr("data-updater")
        let ajaxurl = "/ce/pwd_reset_link/"
        modal = $(this).attr("data-modal")

        let data = {
          'model': $(this).attr('data-model'),
          'ajax': 1,
          'parent': $(this).attr("data-parent"),
          'id': $(this).attr("data-id")
        }

        $.ajax({
          type: "GET",
          url: ajaxurl,
          data: data,
          success: function (response) {

            var span = document.createElement('span')
            span.innerHTML = "Please send the following link to the user<br><br><span id='copy_to'>" + response.url + "</span>&nbsp;&nbsp;<i title='copy to clipboard' class='fas fa fa-paste copy-clipboard' data-clipboard-target='#copy_to' style='cursor: pointer'></i>"

            swal({
              title: '',
              content: span,
              icon: 'success'
            })
          },
          error: function (response) {
            alert(response);
          }
        });
      })

      $(document).on("click", ".ajax-add_new", function () {

        updater = $(this).attr("data-updater")
        let ajaxurl = "/ce/add_new_ajax/"
        modal = $(this).attr("data-modal")

        let data = {
          'model': $(this).attr('data-model'),
          'ajax': 1,
          'parent': $(this).attr("data-parent"),
          'id': $(this).attr("data-id")
        }

        $.ajax({
          type: "GET",
          url: ajaxurl,
          data: data,
          success: function (response) {
            $("#modal_content").html(response);
            $("#" + modal).modal('show');
          },
          error: function (response) {
            alert(response);
          }
        });
      })


      $(document).on('click', 'a.record-details', function () {
          var src = $(this).attr('href');

          $("#details_src").attr('src', src);
          $("#details_src").attr('refresh-target', $(this).attr('refresh-target'));
          $('#details').modal('show');
          return false;
      });

      $("#details").on('hide.bs.modal', function () {
          $("#details_src").attr('src', '');
          
          if($("#details_src").attr('refresh-target')) {
            let ref_target = $("#details_src").attr('refresh-target');

            window[ref_target].ajax.reload(null, false)
          }
      })
      
    });

});