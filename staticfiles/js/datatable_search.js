/* Search behaviour shared by every server-side DataTable.
 *
 * Loaded from cis/header-includes.html (after DataTables), so it reaches
 * every page that extends cis/logged-base.html or cis/logged-base-modal.html.
 *
 * DataTables 1.10 wires its search box through searchDelay, which is a
 * *throttle*, not a debounce: the first keystroke fires a request straight
 * away - a search for "j", the most expensive query a table can run - and
 * typing that runs past the delay fires again with half-typed text. Here the
 * box waits for a 400ms pause in typing instead, Enter (or the browser's
 * clear button) searches immediately, and an unchanged value sends nothing.
 *
 * Because the global box's .DT handlers are removed, a table's own
 * `searchDelay` option has no effect once this script loads.
 *
 * Per-column boxes built in initComplete should call
 * MyceTableSearch.wireColumnInput(column, input) to get the same behaviour.
 *
 * Ported from Canusia/csn PR #37 (package-cis#62).
 */
(function ($) {
  'use strict';

  if (!$ || !$.fn || !$.fn.dataTable) return;

  var DELAY = 400;

  function debounce(fn, wait) {
    var timer;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }

  // Searches `apply(value)` after a pause in typing, or at once on Enter or
  // when the browser's clear button empties the box.
  function wireInput(input, current, apply) {
    var run = function () {
      if (current() !== input.value) apply(input.value);
    };
    var later = debounce(run, DELAY);

    $(input)
      .off('.myceSearch')
      .on('input.myceSearch', later)
      .on('search.myceSearch', run)
      .on('keydown.myceSearch', function (e) {
        if (e.key === 'Enter' || e.keyCode === 13) {
          e.preventDefault();
          run();
        }
      });
  }

  function searchesNames(settings) {
    return settings.aoColumns.some(function (col) {
      return col.bSearchable && /first_name/.test(col.sName || '');
    });
  }

  $(document).on('init.dt', function (e, settings) {
    if (e.namespace !== 'dt' || !settings.oFeatures.bServerSide) return;

    var input = $(settings.nTableWrapper).find('div.dataTables_filter input').get(0);
    if (!input || $(input).data('myceSearch')) return;

    var api = new $.fn.dataTable.Api(settings);

    // Drop DataTables' own throttled handlers (all namespaced .DT).
    $(input).off('.DT').data('myceSearch', true).addClass('myce-search');
    if (!input.getAttribute('placeholder')) {
      input.setAttribute('placeholder', searchesNames(settings)
        ? 'Search… (e.g. first and last name)'
        : 'Search…');
    }

    wireInput(
      input,
      function () { return api.search(); },
      function (value) { api.search(value).draw(); }
    );
  });

  // DataTables centres "Processing…" on the table, which on a long table is
  // below the fold - a search looked like it did nothing for seconds. Pin it
  // to the top of the viewport instead. The leading `body` outranks the
  // bootstrap4 DataTables stylesheet's `div.dataTables_wrapper div...` rule.
  $(function () {
    if (document.getElementById('myce-datatable-search-style')) return;
    var css =
      'body div.dataTables_wrapper div.dataTables_processing {' +
      ' position: fixed; top: 1rem; left: 50%; transform: translateX(-50%);' +
      ' width: auto; height: auto; margin: 0; padding: .5rem 1.25rem; z-index: 1040;' +
      ' background: #fff; border: 1px solid rgba(0,0,0,.125); border-radius: .25rem;' +
      ' box-shadow: 0 .25rem .75rem rgba(0,0,0,.15); white-space: nowrap; }' +
      'body div.dataTables_filter input.myce-search { min-width: 16rem; }';
    var el = document.createElement('style');
    el.id = 'myce-datatable-search-style';
    el.appendChild(document.createTextNode(css));
    document.head.appendChild(el);
  });

  $.extend(true, $.fn.dataTable.defaults, {
    language: {
      processing: '<i class="fas fa-spinner fa-spin"></i>&nbsp;&nbsp;Loading…',
    },
  });

  window.MyceTableSearch = {
    // Same behaviour for the per-column boxes templates build in initComplete.
    // options.regex: pass true to send the column search as a regex (as
    // column.search(value, true) does).
    wireColumnInput: function (column, input, options) {
      var regex = !!(options && options.regex);
      wireInput(
        input,
        function () { return column.search(); },
        function (value) { column.search(value, regex).draw(); }
      );
    },
  };
})(window.jQuery);
