
    jQuery(document).ready(function ($) {

        $("tr.degree-classes").each(function (index, key) {
            let course = $(this).attr('data-course_name')

            if (courses_in_area_of_interest.includes(course)) {
                $(this).addClass('highlight-interest')
            }
        });

        $('[data-show-toggle]').click(function () {
            var foo = $(this).data('show-toggle');
            $('#' + foo).slideToggle();
        });


        $('.academic-tab-toggles a').click(function () {
            var foo = $(this).data('rel');
            $('.academic-tab-toggles a').removeClass('active');
            $(this).addClass('active')
            $('.academic-tab').hide();
            $('.academic-tab.' + foo).show();
        })

        $(document).on("click", "#editCourseDetailsInPlan", function () {

            var term = $("select[name='term']").val();
            if (term == -1) {
                alert("Please select the term you want to take the class");
                $("select[name='term']").focus();

                return;
            }

            event.preventDefault()

            form = $(this).closest('form')

            if ($("input, select, textarea").hasClass('is-invalid'))
                $("input, select, textarea").removeClass('is-invalid')

            if ($("input, select, textarea").next('p').length)
                $("input, select, textarea").nextAll('p').empty();

            let action = $(form).attr('action')
            let first_element = '';

            var formData = new FormData(document.getElementById("frm_manage_course"))
            $.post({
                url: action,
                data: formData,
                processData: false,
                contentType: false,
                error: function (xhr, status, error) {

                    let errors = $.parseJSON(xhr.responseJSON.errors);

                    var span = document.createElement('span')
                    span.innerHTML = xhr.responseJSON.message

                    for (var name in errors) {
                        for (var i in errors[name]) {
                            var $input = $("[name='" + name + "']");
                            $input.addClass('is-invalid');

                            $input.after("<p class='invalid-feedback'><strong class=''>" + errors[name][i].message + "</strong></p>");
                        }

                        if (name == '__all__') {
                            span.innerHTML += "<br><br>" +
                                errors[name][0].message
                        }

                        if (first_element == '')
                            $input.focus()
                        else {
                            first_element = '-'
                        }
                    }

                    swal({
                        title: xhr.responseJSON.message,
                        content: span,
                        icon: 'warning'
                    });
                },
                success: function (response) {
                    swal({
                        title: 'Success',
                        text: response.message,
                        icon: response.status
                    }).then(
                        (value) => {
                            refreshCoursesInPlan();
                            refreshCoursesRequirementsInPlan();
                            $('#modalEditClass').modal('toggle');
                        }
                    )
                }
            })
            return false
        });

        $(document).on("click", "#deleteCourseDetailsInPlan", function () {
            event.preventDefault()

            if(!confirm('Are you sure you want to remove this course from the plan?'))
                return

            var data = {
                "action": "delete_plan_course",
                "plan_course_id": $(this).attr('planclassid'),
                "academic_plan_id": $(this).attr('planid'),
            };

            $.get(ajaxurl, data, function (response) {
                swal({
                        title: 'Success',
                        text: 'Successfully removed class',
                        icon: 'Success'
                    }).then(
                        (value) => {
                            refreshCoursesInPlan();
                            refreshCoursesRequirementsInPlan();
                            $('#modalEditClass').modal('toggle');
                        }
                    )
            });
        });

        $(document).on("click", ".modalSelectClass", function () {
            var data = {
                "action": "get_courses_in_requirement",
                "requirement_id": $(this).attr('reqid'),
                "academic_plan_id": plan_id
            };

            $.get(ajaxurl, data, function (response) {
                $("#modalSelectClass .modal-content").html(response)

                //console.log(school_courses);
                //loop through courses and highlight ones that are running in HS
                var courses = $("#modalSelectClass div.listClasses tr.degree-classes");
                $("#modalSelectClass div.listClasses tr.degree-classes").each(function () {
                    let crs_name = $(this).attr("data-course");
                    //console.log(crs_name);
                    if (school_courses.indexOf(crs_name) != -1)
                        $(this).addClass("highlight-available");
                })

                disableCoursesInPlan();
            });
        });

        $(document).on("click", ".showClassDetails", function () {
            var data = {
                "action": "get_course_details",
                "course_id": $(this).attr('courseid'),
            };


            $.get(ajaxurl, data, function (response) {
                $("#modalClassDetails .modal-content").html(response)
            });
        });

        $(document).on("click", ".showPlanCourseDetails", function () {
            var data = {
                "action": "edit_plan_course_details",
                "plan_course_id": $(this).attr('planclassid'),
            };

            $.get(ajaxurl, data, function (response) {
                $("#modalEditClass .modal-content").html(response)
            });
        });

        $(document).on("click", "#addCourseToPlan", function () {
            var course = $("input[name='course']:checked").val();

            $("#addClass_status").html("");

            if (course == undefined) {
                alert("Please select a course from the list or enter a course name from the catalog");
                return;
            }

            if (course == "") {
                alert("Please enter a course name from the catalog");
                $("input[name='course_name']").focus();
                return;
            }

            var term = $("select[name='term']").val();
            if (term == -1) {
                alert("Please select the term you want to take the class");
                $("select[name='term']").focus();

                return;
            }

            var location = $("select[name='location']").val();
            if (location == -1) {
                alert("Please select the location");
                $("select[name='location']").focus();

                return;
            }

            event.preventDefault()

            form = $(this).closest('form')

            if ($("input, select, textarea").hasClass('is-invalid'))
                $("input, select, textarea").removeClass('is-invalid')

            if ($("input, select, textarea").next('p').length)
                $("input, select, textarea").nextAll('p').empty();

            let action = $(form).attr('action')
            let first_element = '';

            var formData = new FormData(document.getElementById("frm_manage_course"))
            $.post({
                url: action,
                data: formData,
                processData: false,
                contentType: false,
                error: function (xhr, status, error) {

                    let errors = $.parseJSON(xhr.responseJSON.errors);

                    var span = document.createElement('span')
                    span.innerHTML = xhr.responseJSON.message

                    for (var name in errors) {
                        for (var i in errors[name]) {
                            var $input = $("[name='" + name + "']");
                            $input.addClass('is-invalid');

                            $input.after("<p class='invalid-feedback'><strong class=''>" + errors[name][i].message + "</strong></p>");
                        }

                        if (name == '__all__') {
                            span.innerHTML += "<br><br>" +
                                errors[name][0].message
                        }

                        if (first_element == '')
                            $input.focus()
                        else {
                            first_element = '-'
                        }
                    }

                    swal({
                        title: xhr.responseJSON.message,
                        content: span,
                        icon: 'warning'
                    });
                },
                success: function (response) {
                    swal({
                        title: 'Success',
                        text: response.message,
                        icon: response.status
                    }).then(
                        (value) => {
                            refreshCoursesInPlan();
                            refreshCoursesRequirementsInPlan();
                            $('#modalSelectClass').modal('toggle');
                        }
                    )
                }
            })
            return false
        });


        //If EE textbox is clicked on then select radio button
        $(document).on("focus", "input[name='course_name']", function () {
            $("#ee-course").attr("checked", "checked");
        });

        /*
        Mirror course name to radio value
        */
        $(document).on("keyup", "input[name='course_name']", function () {
            $("#ee-course").attr("value", $(this).val());
        });

        /* Write function to disable 'Select' for each category if credits chosen is equal to needed */
        function refreshCategorySelections() {

        }

        $(document).on('click', '.toggle', function (e) {
            e.preventDefault();

            var $this = $(this);

            if ($this.next().hasClass('show')) {
                $this.next().removeClass('show');
                $this.next().slideUp(350);
            } else {
                $this.parent().parent().find('li .inner').removeClass('show');
                //$this.parent().parent().find('li .inner').slideUp(350);
                $this.next().toggleClass('show');
                $this.next().slideDown(350);
            }
        });

    });
