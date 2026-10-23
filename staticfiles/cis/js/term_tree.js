// webapp/cis/staticfiles/cis/js/term_tree.js
/* Tree order for Term DataTables (#112), shared by every tenant's terms table.
 *
 * The server sends `tree_position` (sortable: each term followed by its
 * sub-terms) and `tree_depth` on every term row -- see cis/views/term.py.
 * The table gets a hidden `term.tree` column on tree_position; the Python
 * side (cis.services.term_hierarchy.TREE_COLUMN_HEADER / tree_table_opts)
 * puts its index in `opts.treeColumn`, or null when the profile has none.
 *
 * Loaded by cis/term/terms.html and cis/term/tabs/academic_year/_terms.html
 * before the tenant's terms-table partial, so a tenant's initTermsTable can
 * use window.MyCETermTree without its own script tag:
 *
 *   'term.name': { render: MyCETermTree.render(opts, function (row) { return row.label; }) },
 *   'term.tree': MyCETermTree.columnDef(),
 *   ... exportOptions: MyCETermTree.exportOptions(),
 *   var tree = MyCETermTree.button(opts); if (tree) buttons.push(tree);
 *   MyCETermTree.applyState(dtConfig);
 */
(function () {
  'use strict';

  // v1 = tree order became the default. Saved states from before it keep
  // their old sort; drop that once so everyone lands on the tree. The key and
  // value match the per-tenant copies this replaces, so switching to this
  // file does not reset anyone's saved sort again.
  var STATE_VERSION = 1;

  function inTreeOrder(opts, meta) {
    if (opts.treeColumn == null) return false;
    var order = new $.fn.dataTable.Api(meta.settings).order();
    return order.length > 0 && order[0][0] === opts.treeColumn && order[0][1] === 'asc';
  }

  // Sub-terms are indented only while the table is in tree order; sorted by
  // any other column the indent would mislead.
  function indent(opts, row, meta) {
    if (!row.tree_depth || !inTreeOrder(opts, meta)) return '';
    return new Array(row.tree_depth + 1).join('&nbsp;&nbsp;&nbsp;') + '&#8627;&nbsp;';
  }

  // A column renderer: `displayFn(row)` on screen, indented in tree order;
  // sorting, search and exports get the plain label.
  function render(opts, displayFn) {
    return function (_d, type, row, meta) {
      if (type !== 'display') return row.label;
      return indent(opts, row, meta) + displayFn(row);
    };
  }

  function button(opts) {
    if (opts.treeColumn == null) return null;
    return {
      className: 'btn btn-sm btn-primary text-white text-light',
      text: '<i class="fas fa-sitemap text-white"></i>&nbsp;Tree order',
      titleAttr: 'Sort by parent / sub-term tree',
      action: function (e, dt) { dt.order([[opts.treeColumn, 'asc']]).draw(); },
    };
  }

  // Resets a pre-tree saved sort to the table's default order, once.
  function applyState(dtConfig) {
    dtConfig.stateSaveParams = function (_s, data) { data.treeVersion = STATE_VERSION; };
    dtConfig.stateLoadParams = function (_s, data) {
      if (data.treeVersion !== STATE_VERSION) { data.order = dtConfig.order; }
    };
  }

  window.MyCETermTree = {
    STATE_VERSION: STATE_VERSION,
    indent: indent,
    render: render,
    button: button,
    applyState: applyState,
    // Functions, so two tables on one page never share a mutable object.
    columnDef: function () { return { visible: false, searchable: false }; },
    exportOptions: function () { return { columns: ':visible', orthogonal: 'export' }; },
  };
})();
