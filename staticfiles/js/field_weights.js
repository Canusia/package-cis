/* Drag-and-drop reordering for the student_profile "Profile Fields" setting
 * widget. Each row carries an "editable" checkbox and a weight, plus a caret
 * that expands a hidden detail row holding the field's Label and Help Text.
 * Neither the checkbox nor the detail inputs trigger a re-sort.
 *
 * The setting page injects its form HTML via jQuery .html(), so this file is
 * re-executed every time a setting is opened. All handlers are delegated from
 * `document` and installed once, guarded by window.__fieldWeightsInit.
 *
 * Dragging a row renumbers every weight input in the table (10, 20, 30, ...);
 * typing a weight directly re-sorts the rows on change. Either way the number
 * inputs are what POSTs — row order is presentation only.
 */
(function () {
    if (window.__fieldWeightsInit) {
        return;
    }
    window.__fieldWeightsInit = true;

    var STEP = 10;
    var dragging = null;

    function rows(table) {
        return Array.prototype.slice.call(
            table.querySelectorAll('tbody > tr[data-field]'));
    }

    /* Rewrite every weight input to 10, 20, 30, ... in current DOM order. */
    function renumber(table) {
        rows(table).forEach(function (row, index) {
            var input = row.querySelector('input[type="number"]');
            if (input) {
                input.value = (index + 1) * STEP;
            }
        });
    }

    /* Re-sort rows by their typed weights. Blank weights keep their position
     * relative to the row above, mirroring the server-side ordering rule. */
    function resort(table) {
        var body = table.querySelector('tbody');
        var running = 0;
        var keyed = rows(table).map(function (row, index) {
            var input = row.querySelector('input[type="number"]');
            var raw = input ? parseFloat(input.value) : NaN;
            if (isNaN(raw)) {
                running += 1e-6;
            } else {
                running = raw;
            }
            return { weight: running, index: index, row: row };
        });
        keyed.sort(function (a, b) {
            return a.weight - b.weight || a.index - b.index;
        });
        keyed.forEach(function (item) {
            body.appendChild(item.row);
            var detail = detailFor(item.row);
            if (detail) {
                body.appendChild(detail);
            }
        });
    }

    function closestRow(target) {
        return target && target.closest ? target.closest('tr[data-field]') : null;
    }

    /* Like closestRow, but an expanded detail row resolves to the main row it
     * belongs to. Without this a dragover whose target is inside an expanded
     * detail row finds no row, skips preventDefault(), and the drop indicator
     * stalls while the pointer crosses that row. */
    function dropTargetRow(target) {
        var row = target && target.closest ? target.closest('tr') : null;
        if (!row) {
            return null;
        }
        if (row.dataset && row.dataset.field) {
            return row;
        }
        var owner = row.dataset ? row.dataset.detailFor : null;
        if (!owner) {
            return null;
        }
        var table = row.closest('table');
        return table ? table.querySelector(
            'tbody > tr[data-field="' + owner + '"]') : null;
    }

    function inWidget(el) {
        return el && el.closest && el.closest('table.field-weights-table');
    }

    function detailFor(row) {
        var field = row.dataset ? row.dataset.field : null;
        if (!field) {
            return null;
        }
        var table = row.closest('table');
        return table ? table.querySelector(
            'tr.fw-detail[data-detail-for="' + field + '"]') : null;
    }

    document.addEventListener('click', function (event) {
        var cell = event.target.closest
            ? event.target.closest('td.fw-caret') : null;
        if (!cell || !inWidget(cell)) {
            return;
        }
        var row = cell.closest('tr');
        var detail = row ? detailFor(row) : null;
        if (!detail) {
            return;
        }
        detail.hidden = !detail.hidden;
        cell.innerHTML = detail.hidden ? '▸' : '▾';
    });

    document.addEventListener('dragstart', function (event) {
        var row = closestRow(event.target);
        if (!row || !inWidget(row)) {
            return;
        }
        dragging = row;
        row.classList.add('fw-dragging');
        event.dataTransfer.effectAllowed = 'move';
        // Firefox requires data to be set for the drag to start.
        event.dataTransfer.setData('text/plain', row.dataset.field || '');
    });

    document.addEventListener('dragover', function (event) {
        if (!dragging) {
            return;
        }
        // Resolves an expanded detail row to its owning main row, so crossing
        // one behaves exactly as crossing the row it belongs to.
        var row = dropTargetRow(event.target);
        // The mechanics table has no draggable rows, so it is never a target:
        // its rows live in a different table than the dragged row.
        if (!row || inWidget(row) !== inWidget(dragging)) {
            return;
        }
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        if (row === dragging) {
            // Over the dragged row (or its own detail row): a valid drop
            // target, but nothing to move.
            return;
        }

        // Insert above or below the hovered row depending on pointer position.
        var box = row.getBoundingClientRect();
        var below = event.clientY > box.top + box.height / 2;
        var anchor = below ? (detailFor(row) || row).nextSibling : row;
        var draggingDetail = detailFor(dragging);
        row.parentNode.insertBefore(dragging, anchor);
        if (draggingDetail) {
            row.parentNode.insertBefore(draggingDetail, dragging.nextSibling);
        }
    });

    document.addEventListener('drop', function (event) {
        if (!dragging) {
            return;
        }
        event.preventDefault();
        renumber(inWidget(dragging));
        dragging.classList.remove('fw-dragging');
        dragging = null;
    });

    document.addEventListener('dragend', function () {
        if (dragging) {
            dragging.classList.remove('fw-dragging');
            dragging = null;
        }
    });

    document.addEventListener('change', function (event) {
        var input = event.target;
        if (input && input.type === 'number' && inWidget(input)) {
            resort(inWidget(input));
        }
    });
})();
