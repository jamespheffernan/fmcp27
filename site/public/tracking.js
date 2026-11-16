// Optional X measurement. Nothing from X is loaded until an explicit opt-in.
(function () {
  "use strict";
  if (window.__fmcpXTrackingInitialized) return;
  window.__fmcpXTrackingInitialized = true;

  var KEY = "fmcp27.x-consent.v1";
  var PIXEL = "rj4xn";
  var EVENT = "tw-rj4xn-rj6h1";
  var panel = document.getElementById("consent-panel");
  var settings = document.getElementById("privacy-settings");
  var accept = document.getElementById("consent-accept");
  var reject = document.getElementById("consent-reject");
  var close = document.getElementById("consent-close");
  var description = document.getElementById("consent-state");
  var status = document.getElementById("consent-status");
  if (!panel || !settings || !accept || !reject || !close || !description || !status) return;
  var configured = false;
  var unloading = false;
  var timer;
  var openedFromSettings = false;

  function privacySignal() {
    var dnt = navigator.doNotTrack || window.doNotTrack || navigator.msDoNotTrack;
    return navigator.globalPrivacyControl === true || dnt === "1" || dnt === "yes";
  }

  // Six calendar months, clamped to the last day of the destination month.
  function expiry(savedAt) {
    var date = new Date(savedAt);
    var day = date.getUTCDate();
    date.setUTCDate(1);
    date.setUTCMonth(date.getUTCMonth() + 6);
    var end = new Date(date.getTime());
    end.setUTCMonth(end.getUTCMonth() + 1);
    end.setUTCDate(0);
    date.setUTCDate(Math.min(day, end.getUTCDate()));
    return date.getTime();
  }

  function forget() {
    try { window.localStorage.removeItem(KEY); } catch (_) { /* Storage may be unavailable. */ }
  }

  function readChoice() {
    try {
      var value = JSON.parse(window.localStorage.getItem(KEY));
      if (value && value.version === 1 && (value.choice === "accepted" || value.choice === "rejected") &&
          Number.isFinite(value.savedAt) && value.savedAt <= Date.now() &&
          value.expiresAt === expiry(value.savedAt) && value.expiresAt > Date.now()) return value;
    } catch (_) { /* No stored consent is not consent. */ }
    forget();
    return null;
  }

  var choice = readChoice();

  function allowed() {
    return !unloading && !!choice && choice.choice === "accepted" && choice.expiresAt > Date.now() && !privacySignal();
  }

  function unload() {
    if (!configured || unloading) return;
    unloading = true;
    // Discard any not-yet-sent queue before reloading to unload the third-party library.
    if (window.twq && window.twq.queue) window.twq.queue.length = 0;
    window.twq = function () {};
    window.location.reload();
  }

  function render() {
    var signal = privacySignal();
    accept.disabled = signal;
    description.textContent = signal ? "Your browser asks not to be tracked. X measurement is off." :
      choice ? (choice.choice === "accepted" ? "X measurement is on. Reject to withdraw consent; the page will reload." : "X measurement is off.") :
      "X measurement is off until you accept. Downloads work either way.";
  }

  function startPixel() {
    if (!allowed() || configured) return;
    configured = true;
    // X's standard queue, created only after consent. No automatic download event.
    if (!window.twq) {
      var twq = window.twq = function () {
        twq.exe ? twq.exe.apply(twq, arguments) : twq.queue.push(arguments);
      };
      twq.version = "1.1";
      twq.queue = [];
    }
    window.twq("config", PIXEL);
    var script = document.createElement("script");
    script.async = true;
    script.src = "https://static.ads-twitter.com/uwt.js";
    document.head.appendChild(script);
  }

  function scheduleExpiry() {
    window.clearTimeout(timer);
    if (!choice) return;
    timer = window.setTimeout(sync, Math.min(choice.expiresAt - Date.now(), 2147483647));
  }

  function sync() {
    if (choice && choice.expiresAt <= Date.now()) {
      choice = null;
      forget();
    }
    render();
    if (!allowed()) unload();
    else startPixel();
    scheduleExpiry();
    if (!choice && !privacySignal()) panel.hidden = false;
    settings.setAttribute("aria-expanded", String(!panel.hidden));
  }

  function hidePanel() {
    panel.hidden = true;
    settings.setAttribute("aria-expanded", "false");
    if (openedFromSettings) settings.focus();
    openedFromSettings = false;
  }

  function choose(value) {
    if (value === "accepted" && privacySignal()) return;
    var now = Date.now();
    choice = { version: 1, choice: value, savedAt: now, expiresAt: expiry(now) };
    try { window.localStorage.setItem(KEY, JSON.stringify(choice)); } catch (_) { /* This page only. */ }
    status.textContent = value === "accepted" ? "X measurement accepted." : "X measurement rejected.";
    hidePanel();
    sync();
  }

  accept.addEventListener("click", function () { choose("accepted"); });
  reject.addEventListener("click", function () { choose("rejected"); });
  close.addEventListener("click", hidePanel);
  settings.addEventListener("click", function () {
    sync();
    openedFromSettings = true;
    panel.hidden = false;
    settings.setAttribute("aria-expanded", "true");
    document.getElementById("consent-title").focus();
  });

  document.addEventListener("click", function (event) {
    // Native mouse/touch/keyboard activation only. Never replay earlier clicks,
    // intercept navigation, wait for the pixel, or count other links as downloads.
    if (!event.isTrusted || event.defaultPrevented || event.button !== 0) return;
    var link = event.target && event.target.closest && event.target.closest('a[href="/download/FMCP27-mac.zip"][download]');
    if (!link) return;
    sync();
    if (!allowed()) return;
    try { window.twq("event", EVENT, {}); } catch (_) { /* Measurement must not affect the download. */ }
  });

  window.addEventListener("storage", function (event) {
    if (event.key !== KEY && event.key !== null) return;
    choice = readChoice();
    sync();
  });
  window.addEventListener("pageshow", sync);
  window.addEventListener("focus", sync);
  document.addEventListener("visibilitychange", sync);
  settings.hidden = false;
  sync();
})();
