// Basic site statistics, independent of optional X advertising measurement.
(function () {
  "use strict";
  if (window.__fmcpAnalyticsInitialized) return;
  window.__fmcpAnalyticsInitialized = true;
  // Never count Pages previews or local development as production traffic.
  if (window.location.hostname !== "fmcp27.com") return;
  var KEY = "fmcp27.analytics-opt-out.v1";
  var button = document.getElementById("analytics-toggle");
  var status = document.getElementById("analytics-status");
  var dnt = navigator.doNotTrack || window.doNotTrack || navigator.msDoNotTrack;
  var signal = navigator.globalPrivacyControl === true || dnt === "1" || dnt === "yes";
  var optedOut = false;
  try { optedOut = window.localStorage.getItem(KEY) === "1"; }
  catch (_) { optedOut = true; }
  var enabled = !signal && !optedOut;
  if (button) {
    button.hidden = false;
    button.disabled = signal;
    button.textContent = enabled ? "Turn off site analytics" : "Turn on site analytics";
    button.addEventListener("click", function () {
      try {
        window.localStorage.setItem(KEY, enabled ? "1" : "0");
        window.sessionStorage.removeItem("lodd_sid");
        window.location.reload();
      } catch (_) {
        if (status) status.textContent = "Your browser could not save this preference. Block lodd.dev in your browser to disable analytics.";
      }
    });
  }
  if (status) status.textContent = signal ? "Site analytics is off because of your browser privacy signal." :
    enabled ? "Basic site analytics is on. You can turn it off here." : "Site analytics is off.";
  window.addEventListener("storage", function (event) {
    if (event.key === KEY || event.key === null) window.location.reload();
  });
  if (!enabled) return;
  window.ca = window.ca || { q: [], track: function () { this.q.push(arguments); } };
  document.addEventListener("click", function (event) {
    if (!event.isTrusted || event.defaultPrevented || event.button !== 0) return;
    var link = event.target && event.target.closest && event.target.closest('a[href="/download/FMCP27-mac.zip"][download]');
    if (!link) return;
    // Do not intercept or delay the download. This is a click, not completion.
    try { window.ca.track("download_mac", { file: "FMCP27-mac.zip", platform: "mac_arm64", placement: "hero" }); }
    catch (_) { /* Analytics must never break the download. */ }
  });
  var script = document.createElement("script");
  script.async = true;
  script.src = "https://lodd.dev/tracking/v1.js";
  script.setAttribute("data-site-id", "6877b596-fab6-4e08-be19-0ee01330148f");
  script.setAttribute("data-tracking-secret", "08dfbcfc0bd269a0035f841e1afb01425aefdcfeabf26ac2947c329ade2202a2");
  document.head.appendChild(script);
})();
