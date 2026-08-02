// Courses index page: post-bulk-action callback.
// course_actions bulk handlers respond {outcome:'call', fn:'onBulkActionComplete'}.
// The page now hosts several independently-initialized DataTables, so reload
// them all rather than named globals.
function onBulkActionComplete(args) {
    if (window.jQuery && $.fn.dataTable) {
        $($.fn.dataTable.tables(true)).each(function () {
            var dt = $(this).DataTable();
            dt.rows({ selected: true }).deselect();
            dt.ajax.reload(null, false);
        });
    }
    if (args && args.message) {
        var span = document.createElement('span');
        span.innerHTML = args.message;
        swal({ title: args.title || 'Done', content: span, icon: args.status || 'success' });
    }
}
