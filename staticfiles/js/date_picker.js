// Open a native date field's picker from anywhere in the input.
//
// Chrome, Edge and Safari only open the calendar when the user hits the small
// icon at the right-hand edge; clicking the text area just places a caret.
// `HTMLInputElement.showPicker()` opens it directly.
//
// Bound to `click`, deliberately NOT to `focus`: showPicker() requires
// transient user activation, and focus arriving by keyboard (tabbing into the
// field) or programmatically is not activation -- Chrome throws NotAllowedError
// and, worse, a picker that pops open while someone is tabbing through the form
// is a trap. Clicking is an unambiguous "I want the calendar".
//
// Delegated from the document so it covers fields that are rendered late
// (conditionally shown blocks, formset rows) without needing to re-bind.
(function () {
  'use strict';

  document.addEventListener('click', function (event) {
    var el = event.target;

    if (!el || el.tagName !== 'INPUT' || el.type !== 'date') return;
    if (el.disabled || el.readOnly) return;
    // Firefox < 101 and older Safari have no showPicker(); there the built-in
    // icon remains the way in, which is the pre-existing behaviour.
    if (typeof el.showPicker !== 'function') return;

    try {
      el.showPicker();
    } catch (e) {
      // NotAllowedError (no user activation) or InvalidStateError (the icon
      // already opened it). The native control still works either way, so
      // there is nothing to recover from.
    }
  });
})();
