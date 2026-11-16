const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../public/tracking.js'), 'utf8');
const KEY = 'fmcp27.x-consent.v1';

function harness(options = {}) {
  let now = options.now ?? Date.UTC(2026, 0, 31, 12);
  const store = options.store || new Map();
  const network = [];
  const timers = new Map();
  let reloads = 0;
  let nextTimer = 1;
  function node(id) {
    return {
      id, hidden: true, disabled: false, attrs: {}, listeners: {},
      addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
      setAttribute(key, value) { this.attrs[key] = value; },
      focus() { this.focused = true; },
      emit(type, event = {}) { for (const fn of this.listeners[type] || []) fn(event); }
    };
  }
  const ids = Object.fromEntries(['consent-panel', 'privacy-settings', 'consent-accept', 'consent-reject', 'consent-close', 'consent-state', 'consent-status', 'consent-title'].map(id => [id, node(id)]));
  const document = Object.assign(node('document'), {
    getElementById(id) { return ids[id]; },
    createElement(tag) { assert.equal(tag, 'script'); return {}; },
    head: { appendChild(script) { network.push(script.src); } }
  });
  const navigator = { globalPrivacyControl: options.gpc || false, doNotTrack: options.dnt };
  const window = Object.assign(node('window'), {
    localStorage: {
      getItem(key) { if (options.storageBlocked) throw Error('blocked'); return store.get(key) || null; },
      setItem(key, value) { if (options.storageBlocked) throw Error('blocked'); store.set(key, value); },
      removeItem(key) { if (options.storageBlocked) throw Error('blocked'); store.delete(key); }
    },
    setTimeout(fn, delay) { const id = nextTimer++; timers.set(id, { fn, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    location: { reload() { reloads++; } }
  });
  class Clock extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  }
  const context = vm.createContext({ window, document, navigator, Date: Clock, console });
  vm.runInContext(source, context);
  function clickDownload(overrides = {}) {
    const event = Object.assign({ isTrusted: true, defaultPrevented: false, button: 0, target: { closest(selector) { assert.equal(selector, 'a[href="/download/FMCP27-mac.zip"][download]'); return {}; } } }, overrides);
    document.emit('click', event);
    return event;
  }
  return {
    ids, store, window, navigator, document, network, timers,
    get reloads() { return reloads; },
    click(id) { ids[id].emit('click'); }, clickDownload,
    calls() { return window.twq?.queue ? Array.from(window.twq.queue, args => Array.from(args)) : []; },
    advance(ms) { now += ms; },
    runTimers() { const current = [...timers.values()]; timers.clear(); current.forEach(timer => timer.fn()); },
    rerun() { vm.runInContext(source, context); }
  };
}

function configCalls(h) { return h.calls().filter(args => args[0] === 'config'); }
function events(h) { return h.calls().filter(args => args[0] === 'event'); }

test('no X script, queue or event before consent; downloads are not blocked or replayed', () => {
  const h = harness();
  const event = h.clickDownload({ preventDefault() { assert.fail('download must not be blocked'); } });
  assert.equal(event.defaultPrevented, false);
  assert.deepEqual(h.network, []);
  assert.equal(h.window.twq, undefined);
  assert.equal(h.ids['consent-panel'].hidden, false);
  h.click('consent-accept');
  assert.equal(events(h).length, 0);
});

test('reject persists and has no network on this or a later page', () => {
  const h = harness();
  h.click('consent-reject');
  h.clickDownload();
  assert.deepEqual(h.network, []);
  assert.equal(JSON.parse(h.store.get(KEY)).choice, 'rejected');
  const next = harness({ store: h.store });
  next.clickDownload();
  assert.deepEqual(next.network, []);
  assert.equal(next.ids['consent-panel'].hidden, true);
});

test('accept configures once, including repeated acceptance, lifecycle events and duplicate script execution', () => {
  const h = harness();
  h.click('consent-accept');
  h.click('privacy-settings');
  h.click('consent-accept');
  h.window.emit('pageshow');
  h.window.emit('focus');
  h.rerun();
  assert.deepEqual(h.network, ['https://static.ads-twitter.com/uwt.js']);
  assert.equal(configCalls(h).length, 1);
  assert.deepEqual(configCalls(h)[0], ['config', 'rj4xn']);
  assert.equal(events(h).length, 0);
});

test('exactly one custom event with empty parameters for each native download activation', () => {
  const h = harness();
  h.click('consent-accept');
  h.clickDownload();
  h.clickDownload(); // Also represents a native keyboard activation (button === 0).
  assert.equal(events(h).length, 2);
  for (const event of events(h)) {
    assert.equal(event[1], 'tw-rj4xn-rj6h1');
    assert.equal(JSON.stringify(event[2]), '{}');
    assert.equal(event.length, 3);
  }
});

test('ordinary links, missing exact download target, synthetic clicks and cancelled actions do not count', () => {
  const h = harness();
  h.click('consent-accept');
  h.clickDownload({ target: { closest() { return null; } } });
  h.clickDownload({ target: {} });
  h.clickDownload({ isTrusted: false });
  h.clickDownload({ defaultPrevented: true });
  h.clickDownload({ button: 1 });
  assert.equal(events(h).length, 0);
});

test('remembered acceptance configures once per page, without any download event', () => {
  const first = harness();
  first.click('consent-accept');
  const next = harness({ store: first.store });
  assert.equal(next.network.length, 1);
  assert.equal(configCalls(next).length, 1);
  assert.equal(events(next).length, 0);
  assert.equal(next.ids['consent-panel'].hidden, true);
});

test('choice expires after six calendar months, including a clamped month end', () => {
  const h = harness({ now: Date.UTC(2026, 7, 31, 12) });
  h.click('consent-accept');
  const choice = JSON.parse(h.store.get(KEY));
  assert.equal(choice.expiresAt, Date.UTC(2027, 1, 28, 12));
  const expired = harness({ store: h.store, now: choice.expiresAt });
  assert.deepEqual(expired.network, []);
  assert.equal(expired.ids['consent-panel'].hidden, false);
  assert.equal(expired.store.has(KEY), false);
});

test('expiration while a page remains open unloads X and clears queued events', () => {
  const h = harness();
  h.click('consent-accept');
  h.advance(366 * 86400000);
  h.runTimers();
  assert.equal(h.reloads, 1);
  assert.equal(h.store.has(KEY), false);
  h.clickDownload();
  assert.equal(events(h).length, 0);
});

test('settings are keyboard-native controls; reject withdraws, persists and reloads to unload', () => {
  const h = harness();
  h.click('consent-accept');
  h.clickDownload();
  const queue = h.window.twq.queue;
  h.click('privacy-settings');
  assert.equal(h.ids['consent-panel'].hidden, false);
  assert.equal(h.ids['consent-title'].focused, true);
  h.click('consent-reject');
  assert.equal(h.reloads, 1);
  assert.equal(queue.length, 0);
  assert.equal(JSON.parse(h.store.get(KEY)).choice, 'rejected');
  assert.equal(h.ids['privacy-settings'].focused, true);
  assert.equal(harness({ store: h.store }).network.length, 0);
});

test('GPC and DNT veto fresh and remembered consent', () => {
  for (const signal of [{ gpc: true }, { dnt: '1' }, { dnt: 'yes' }]) {
    const first = harness();
    first.click('consent-accept');
    const h = harness({ ...signal, store: first.store });
    h.click('privacy-settings');
    h.click('consent-accept');
    h.clickDownload();
    assert.equal(h.ids['consent-accept'].disabled, true);
    assert.deepEqual(h.network, []);
    assert.equal(h.window.twq, undefined);
  }
});

test('other-tab withdrawal reloads a previously accepted page', () => {
  const h = harness();
  h.click('consent-accept');
  const other = harness({ store: h.store });
  other.click('consent-reject');
  h.window.emit('storage', { key: KEY });
  assert.equal(h.reloads, 1);
});

test('blocked or malformed storage fails closed; explicit in-page acceptance still works', () => {
  for (const value of ['not json', JSON.stringify({ choice: 'accepted', expiresAt: Infinity }), JSON.stringify({ version: 1, choice: 'accepted', savedAt: Date.UTC(2099, 0, 1), expiresAt: Date.UTC(2100, 0, 1) })]) {
    const h = harness({ store: new Map([[KEY, value]]) });
    assert.deepEqual(h.network, []);
  }
  const h = harness({ storageBlocked: true });
  assert.deepEqual(h.network, []);
  h.click('consent-accept');
  h.clickDownload();
  assert.equal(events(h).length, 1);
  assert.equal(harness({ storageBlocked: true }).network.length, 0);
});

test('HTML keeps direct no-JS download and deferred first-party tracking; CSP remains narrow', () => {
  const publicDir = path.join(__dirname, '../public');
  const html = fs.readFileSync(path.join(publicDir, 'index.html'), 'utf8');
  assert.match(html, /<a class="dl" href="\/download\/FMCP27-mac.zip" download>/);
  assert.match(html, /<script src="\/tracking.js\?v=[a-f0-9]+" defer><\/script>/);
  assert.doesNotMatch(html, /<script[^>]*>\s*[^<\s]/);
  for (const id of ['consent-accept', 'consent-reject', 'privacy-settings']) {
    assert.match(html, new RegExp('<button[^>]+type="button"[^>]+id="' + id + '"'));
  }
  const headers = fs.readFileSync(path.join(publicDir, '_headers'), 'utf8');
  assert.match(headers, /script-src 'self' https:\/\/static.ads-twitter.com https:\/\/lodd.dev;/);
  assert.doesNotMatch(headers, /unsafe-inline|unsafe-eval/);
  for (const directive of ["default-src 'none'", "style-src 'self'", "font-src 'self'", "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'", 'upgrade-insecure-requests']) assert.ok(headers.includes(directive));
});
