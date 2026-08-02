function initChangeHistoryTable(tableId, apiUrl, options) {
    var showSourceBadge = (options || {}).showSourceBadge || false;
    // Which serializer field the last column renders. Defaults to the full
    // record snapshot ('value'); pass 'changes' to show the field-level diff
    // (what data was changed) instead.
    var changesColumn = (options || {}).changesColumn || 'value';

    var $table = $('#' + tableId);
    if (!$table.length) return;

    // tab_loader.js injects this fragment (and runs this script) from INSIDE its
    // own shown.bs.tab handler — i.e. after that event already fired — and also
    // for a deep-linked/active tab during page load. Binding another
    // shown.bs.tab here would miss the current show, so build the table now.
    // Guard against re-init if the fragment is reloaded (window.reloadTab).
    if ($.fn.dataTable.isDataTable($table)) {
        $table.DataTable().ajax.reload(null, false);
        return;
    }

    $table.DataTable({
        dom: 'B<"float-left mt-3 mb-3"l><"row clear">rt<"row"<"col-6"i><"col-6 float-right"p>>',
        searching: false,
        buttons: [
            {
                extend: 'csv', className: 'btn btn-sm btn-primary text-white text-light',
                text: '<i class="fas fa-file-csv text-white"></i>&nbsp;CSV',
                titleAttr: 'Export results to CSV'
            },
            {
                extend: 'print', className: 'btn btn-sm btn-primary text-white text-light',
                text: '<i class="fas fa-print text-white"></i>&nbsp;Print',
                titleAttr: 'Print'
            }
        ],
        lengthMenu: [30, 50, 100],
        order: [[0, 'desc']],
        ajax: {
            url: apiUrl,
            dataSrc: 'data'
        },
        columns: [
            {
                data: 'history_date',
                render: function (data, type) {
                    if (type === 'sort' || type === 'type') return data;
                    var d = new Date(data);
                    return d.toLocaleString();
                }
            },
            { data: 'history_user' },
            {
                data: 'history_type',
                render: function (data, type, row) {
                    var sourceBadge = '';
                    if (showSourceBadge) {
                        sourceBadge = row.source_model === 'User'
                            ? '<span class="badge badge-info">User</span> '
                            : '<span class="badge badge-primary">Student</span> ';
                    }
                    var actionBadge;
                    if (data === 'Created') {
                        actionBadge = '<span class="badge badge-success">Created</span>';
                    } else if (data === 'Changed') {
                        actionBadge = '<span class="badge badge-warning">Changed</span>';
                    } else if (data === 'Deleted') {
                        actionBadge = '<span class="badge badge-danger">Deleted</span>';
                    } else {
                        actionBadge = data;
                    }
                    return sourceBadge + actionBadge;
                }
            },
            {
                data: changesColumn,
                render: function (data) {
                    if (data == null || data === '') return '';
                    var preview = data.length > 80 ? data.substring(0, 80) + '...' : data;
                    return '<code class="history-value-preview" style="cursor:pointer; font-size:0.85em;" title="Click to view full details">' +
                        $('<span>').text(preview).html() + '</code>';
                }
            }
        ]
    });

    // Preview -> full text. Namespaced + rebound per table so reloading the tab
    // doesn't stack duplicate handlers.
    $(document).off('click.chg_' + tableId).on('click.chg_' + tableId, '#' + tableId + ' .history-value-preview', function () {
        var row = $(this).closest('tr');
        var rowData = $('#' + tableId).DataTable().row(row).data();
        if (rowData) {
            swal({ title: 'Details', text: rowData[changesColumn], customClass: 'swal-wide' });
        }
    });
}
