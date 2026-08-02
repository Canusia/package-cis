/* Comparison panel: dimension-agnostic. Reads its dimension + API URL from
 * data attributes, so the same file drives /ce/terms/ and /ce/academic_years/.
 */
(function (window, $) {
    'use strict';

    // The chart shows only the top TOP_N categories (see sortedCategories).
    // Any metric whose category count can exceed TOP_N must use the
    // 'chart_and_table' presentation so its table discloses the remainder.
    var TOP_N = 12;
    var COLORS = ['#4e73df', '#1cc88a', '#f6c23e'];  // one per selected record
    var MAX_RECORDS = 3;

    /** Escape a user-controlled string for safe HTML insertion via a
     *  text-node round trip -- never concatenate raw strings into .html(). */
    function escapeHtml(value) {
        return $('<div>').text(value).html();
    }

    /** The JS owns category ordering: totals descending, ties broken by
     *  label ascending. The chart truncates to TOP_N categories; the table
     *  shows every category using this same order. */
    function sortedCategories(rows) {
        var totals = {};
        rows.forEach(function (r) {
            totals[r.category] = (totals[r.category] || 0) + r.value;
        });
        return Object.keys(totals).sort(function (a, b) {
            if (totals[b] !== totals[a]) { return totals[b] - totals[a]; }
            return a < b ? -1 : (a > b ? 1 : 0);
        });
    }

    function valueLookup(rows) {
        var map = {};
        rows.forEach(function (r) {
            map[r.dimension_id + '' + r.category] = r.value;
        });
        return function (dimId, category) {
            return map[dimId + '' + category] || 0;
        };
    }

    function drawChart(canvas, dimensions, rows, existingChart) {
        if (existingChart) { existingChart.destroy(); }
        var categories = sortedCategories(rows).slice(0, TOP_N);
        var lookup = valueLookup(rows);
        return new window.Chart(canvas, {
            type: 'bar',
            data: {
                labels: categories,
                datasets: dimensions.map(function (d, i) {
                    return {
                        label: d.label,
                        backgroundColor: COLORS[i % COLORS.length],
                        data: categories.map(function (c) {
                            return lookup(d.id, c);
                        })
                    };
                })
            },
            options: {
                responsive: true,
                scales: { y: { beginAtZero: true } }
            }
        });
    }

    function drawTable($table, dimensions, rows) {
        var lookup = valueLookup(rows);
        var head = '<tr><th>Category</th>' + dimensions.map(function (d) {
            return '<th>' + escapeHtml(d.label) + '</th>';
        }).join('') + '<th>Total</th></tr>';

        var body = sortedCategories(rows).map(function (c) {
            var values = dimensions.map(function (d) { return lookup(d.id, c); });
            var total = values.reduce(function (a, b) { return a + b; }, 0);
            return '<tr><td>' + escapeHtml(c) + '</td>' +
                values.map(function (v) { return '<td>' + v + '</td>'; }).join('') +
                '<td>' + total + '</td></tr>';
        }).join('');

        $table.html('<thead>' + head + '</thead><tbody>' + body + '</tbody>');
    }

    function downloadPng(canvas, filename) {
        var link = document.createElement('a');
        link.download = filename + '.png';
        link.href = canvas.toDataURL('image/png');
        link.click();
    }

    window.initComparisonPanel = function (root) {
        var $root = $(root);
        var apiUrl = $root.data('api-url');
        var charts = {};

        function selectedQuery() {
            return $root.find('input[name=id]:checked, ' +
                'input[name=status]:checked, ' +
                'input[name=campus]:checked, ' +
                'select[name=campus], ' +
                'input[name=section_status]:checked').serialize();
        }

        function enforceMax() {
            var $ids = $root.find('input[name=id]');
            var atMax = $ids.filter(':checked').length >= MAX_RECORDS;
            $ids.not(':checked').prop('disabled', atMax);
            $root.find('.compare-limit-hint').toggle(atMax);
        }

        function render(payload) {
            $root.find('.compare-error').hide();
            Object.keys(payload.metrics).forEach(function (key) {
                var metric = payload.metrics[key];
                var $card = $root.find('[data-metric="' + key + '"]');
                var hasRows = metric.rows.length > 0;

                $card.find('.compare-empty').toggle(!hasRows);
                $card.find('.compare-chart-wrap, .compare-table-wrap')
                    .toggle(hasRows);
                if (!hasRows) {
                    if (charts[key]) { charts[key].destroy(); delete charts[key]; }
                    return;
                }

                var canvas = $card.find('canvas')[0];
                charts[key] = drawChart(
                    canvas, payload.dimensions, metric.rows, charts[key]);

                if (metric.presentation === 'chart_and_table') {
                    drawTable($card.find('table'), payload.dimensions,
                        metric.rows);
                }
            });
        }

        function showError(xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.error) ||
                'Unable to load the comparison.';
            $root.find('.compare-error').text(msg).show();
        }

        function run(pushState) {
            var query = selectedQuery();
            if (!$root.find('input[name=id]:checked').length) {
                $root.find('.compare-error')
                    .text('Select at least one to compare.').show();
                return;
            }
            if (pushState) {
                window.history.pushState({}, '', '?' + query + '#compare');
            }
            $.getJSON(apiUrl + '?' + query).done(render).fail(showError);
        }

        function rehydrateFromUrl() {
            var params = new URLSearchParams(window.location.search);
            if (!params.getAll('id').length) { return false; }
            ['id', 'status', 'campus', 'section_status'].forEach(function (n) {
                var values = params.getAll(n);
                if (!values.length) { return; }
                $root.find('input[name=' + n + ']').each(function () {
                    $(this).prop('checked', values.indexOf(this.value) !== -1);
                });
            });
            var campusSel = params.getAll('campus');
            if (campusSel.length) {
                $root.find('select[name=campus]').val(campusSel[0]);
            }
            enforceMax();
            return true;
        }

        $root.on('change', 'input[name=id]', enforceMax);

        // Academic-years panel: a campus selector drives the record list. Pick a
        // campus -> show + auto-select (up to MAX_RECORDS) the academic years for
        // that campus PLUS any with no campus; hide/deselect the rest.
        $root.on('change', '.compare-campus-select', function () {
            var campus = $(this).val();
            var $ids = $root.find('input[name=id]');
            $ids.prop('checked', false).prop('disabled', false);
            var checked = 0;
            $ids.each(function () {
                var rc = $(this).attr('data-campus') || '';
                var match = campus !== '' && (rc === campus || rc === '');
                $(this).closest('.form-check').toggle(campus === '' || match);
                if (match && checked < MAX_RECORDS) {
                    $(this).prop('checked', true);
                    checked++;
                }
            });
            enforceMax();
        });

        $root.on('click', '.compare-run', function (e) {
            e.preventDefault();
            run(true);
        });
        $root.on('click', '.compare-png', function (e) {
            e.preventDefault();
            var key = $(this).closest('[data-metric]').data('metric');
            downloadPng($(this).closest('[data-metric]').find('canvas')[0], key);
        });
        $root.on('click', '.compare-print', function (e) {
            e.preventDefault();
            window.print();
        });

        enforceMax();
        if (rehydrateFromUrl()) { run(false); }
    };
}(window, jQuery));
