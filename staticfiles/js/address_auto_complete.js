/**
 * Address Autocomplete jQuery Plugin
 *
 * Usage:
 * $("#id_mailing_address").addressAutocomplete({
 * lookupUrl: "/student/address_lookup/",
 * countryInput: "#id_country_of_residence"
 * });
 */
(function ($) {
  $.fn.addressAutocomplete = function (options) {
    var defaults = {
      lookupUrl: "",
      countryInput: "#id_country_of_residence",
      cityInput: "#id_city",
      stateInput: "#id_state",
      zipInput: "#id_zip_code",
      address2Input: "",  // optional — if set and the element exists, secondary
                          // goes into this field instead of the main input.
      menuWidth: "50%",
      debounceMs: 1500, // Consider lowering this to 300-500 for a snappier feel
      minLength: 5,
    };

    var settings = $.extend({}, defaults, options);

    function hasAddress2() {
      return settings.address2Input && $(settings.address2Input).length > 0;
    }

    return this.each(function () {
      var input = $(this);
      var menu = $('<ul class="us-autocomplete-pro-menu" style="display:none;"></ul>');
      var typingTimer; // Timer variable for our new debounce logic

      input.after(menu);
      menu.menu({
        select: function (event, ui) {
          handleSelect(ui);
        },
      });
      menu.css("width", settings.menuWidth);

      function showLoading() {
        menu.empty();
        menu.append(
          "<li class='ui-state-disabled' style='opacity: 0.7;'><div>" +
            "<i class='fas fa-spinner fa-spin' style='margin-right: 8px;'></i> Loading suggestions..." +
            "</div></li>"
        );
        menu.show();
        menu.menu("refresh");
      }

      function noSuggestions() {
        menu.empty();
        menu.append("<li class='ui-state-disabled'><div>No Suggestions Found</div></li>");
        menu.menu("refresh");
      }

      function sessionExpired() {
        menu.empty();
        menu.append(
          "<li class='ui-state-disabled'><div>You have been logged out due to inactivity. Please reload the page and try again.</div></li>"
        );
        menu.menu("refresh");
      }

      function clearAddressData() {
        $(settings.cityInput).val("");
        $(settings.stateInput).val("");
        $(settings.zipInput).val("");
        if (settings.address2Input) {
          $(settings.address2Input).val("");
        }
      }

      function getSuggestions(search, selected) {
        var countryCode = $(settings.countryInput).val();

        // Note: minLength check and showLoading() were removed from here 
        // because they are now handled immediately by the event listener.

        $.ajax({
          url: settings.lookupUrl,
          data: {
            search: search,
            country_code: countryCode ? countryCode : "",
            selected: selected ? selected : "",
          },
          success: function (data) {
            if (data.suggestions) {
              buildMenu(data.suggestions);
            } else if (data.session_expired) {
              sessionExpired();
            } else {
              noSuggestions();
            }
          },
          error: function () {
            noSuggestions();
          },
        });
      }

      function buildAddress(suggestion) {
        var whiteSpace = "";

        if (suggestion.secondary || suggestion.entries > 1) {
          if (suggestion.entries > 1) {
            suggestion.secondary = suggestion.secondary ? suggestion.secondary : "";
            suggestion.secondary += " (" + suggestion.entries + " more entries)";
          }
          whiteSpace = " ";
        }

        var address =
          suggestion.street_line +
          whiteSpace +
          (suggestion.secondary ? suggestion.secondary + ", " : ", ") +
          (suggestion.city ? suggestion.city + ", " : "") +
          (suggestion.state ? suggestion.state + " " : "") +
          (suggestion.zipcode ? suggestion.zipcode : "");

        var inputAddress = input.val();
        for (var i = 0; i < address.length; i++) {
          if (
            typeof inputAddress[i] === "undefined" ||
            address[i].toLowerCase() !== inputAddress[i].toLowerCase()
          ) {
            address = [address.slice(0, i), "<b>", address.slice(i)].join("");
            break;
          }
        }
        return address;
      }

      function buildMenu(suggestions) {
        menu.empty();

        if (suggestions.length === 1 && !suggestions[0].address_id) {
          input.val(suggestions[0].street_line);
          if (settings.address2Input) {
            $(settings.address2Input).val(suggestions[0].secondary || "");
          }
          $(settings.cityInput).val(suggestions[0].city);
          $(settings.stateInput).val(suggestions[0].state);
          $(settings.zipInput).val(suggestions[0].zipcode);
          menu.hide();
          return;
        }

        suggestions.forEach(function (suggestion) {
          var caret =
            suggestion.entries > 1
              ? '<span class="ui-menu-icon ui-icon ui-icon-caret-1-e"></span>'
              : "";

          // Pipe-delimited payload (|) because secondary/city/state can contain commas.
          // Format: street_line|secondary|city|state|zipcode|address_id
          var dataAddress =
            (suggestion.street_line || "") + "|" +
            (suggestion.secondary || "") + "|" +
            (suggestion.city || "") + "|" +
            (suggestion.state || "") + "|" +
            (suggestion.zipcode || "") + "|" +
            (suggestion.address_id || "");

          menu.append(
            "<li><div data-address='" +
              dataAddress +
              "' data-address_id='" +
              (suggestion.address_id ? suggestion.address_id : "") +
              "'>" +
              caret +
              buildAddress(suggestion) +
              "</b></div></li>"
          );
        });
        menu.menu("refresh");
      }

      function handleSelect(ui) {
        var text = ui.item[0].innerText;
        var address = ui.item[0].childNodes[0].dataset.address.split("|");
        var addressId = ui.item[0].childNodes[0].dataset.address_id;

        // split() layout: [street_line, secondary, city, state, zipcode, address_id]
        var streetLine = address[0] || "";
        var secondary  = address[1] || "";
        var city       = address[2] || "";
        var state      = address[3] || "";
        var zipcode    = address[4] || "";

        if (addressId) {
          var sel = addressId.replace(",", "");
          getSuggestions(streetLine, sel);
          return;
        }

        var moreEntriesPattern = /(?:\ more\ entries\))/;
        var hasMoreEntries = text.search(moreEntriesPattern) !== -1;

        if (hasAddress2()) {
          // Separate fields: main input gets just the street line.
          input.val(streetLine);
          $(settings.address2Input).val(hasMoreEntries ? "" : secondary);
        } else {
          // Legacy behavior: merge secondary into the main input.
          input.val(streetLine + (secondary ? " " + secondary : ""));
        }
        $(settings.cityInput).val(city);
        $(settings.stateInput).val(state);
        $(settings.zipInput).val(zipcode);

        if (!hasMoreEntries) {
          menu.hide();
        } else {
          // Drilling into a multi-entry group — search with the combined text
          // Smarty expects as `selected`.
          if (!hasAddress2()) {
            input.val(streetLine + (secondary ? " " + secondary : "") + " ");
          }
          var selected = text.replace(" more entries", "").replace(",", "");
          getSuggestions(streetLine, selected);
        }
      }

      // --- NEW EVENT LISTENER LOGIC ---
      
      // Handle typing (input event catches paste, autocomplete, and typing)
      input.on("input", function () {
        var textInput = input.val();

        // 1. Clear the timer on every keystroke
        clearTimeout(typingTimer);

        // 2. Handle empty input
        if (textInput.length === 0) {
          clearAddressData();
          menu.hide();
          return;
        }

        // 3. Wait for the minimum length
        if (textInput.length < settings.minLength) {
          menu.hide();
          return;
        }

        // 4. Show loading immediately once we hit 5+ characters
        menu.show();
        showLoading();

        // 5. Delay the actual API call
        typingTimer = setTimeout(function () {
          getSuggestions(textInput);
        }, settings.debounceMs);
      });

      // Handle keyboard navigation separately
      input.on("keydown", function (event) {
        if (event.key === "ArrowDown" && menu.is(":visible")) {
          event.preventDefault(); // Stop cursor from jumping to the end of the input
          menu.focus();
          menu.menu("focus", null, menu.menu().find(".ui-menu-item").first());
        }
      });

      // Hide suggestions when user leaves the input or clicks elsewhere.
      input.on("blur", function () {
        setTimeout(function () {
          menu.hide();
        }, 150);
      });

      $(document).on("mousedown", function (event) {
        if (!menu.is(event.target) && menu.has(event.target).length === 0 && !input.is(event.target)) {
          menu.hide();
        }
      });
      
    });
  };
})(jQuery);