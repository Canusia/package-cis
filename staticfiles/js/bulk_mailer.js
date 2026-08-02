$(function () {

  $(document).on('change', "#id_datasource", function() {
      let val = $(this).val()

      if(val == 'file_upload') {
        $("#div_id_file").removeClass('d-none')
        $("#datasource_customizer").addClass('d-none')
      } else {
        $("#div_id_file").addClass('d-none')

        let ajaxurl = "/ce/announcements/bulk_message/get_datasource_filters";
        let data = {
          "datasource": val
        }
        $.get(ajaxurl, data, function (response) {
          console.log(response)
          $("#datasource_customizer").html(response.filter)
        });
        // get customizer for data source
        $("#datasource_customizer").removeClass('d-none')


      }
  })
})
