// Tables reflow into grids at phone width. Some browsers drop table semantics
// when table elements change display, so state the roles explicitly.
(function () {
  function role(root, selector, name) {
    root.querySelectorAll(selector).forEach(function (el) { el.setAttribute("role", name); });
  }
  document.querySelectorAll("table").forEach(function (table) {
    table.setAttribute("role", "table");
    role(table, "thead, tbody", "rowgroup");
    role(table, "tr", "row");
    role(table, "thead th", "columnheader");
    role(table, "tbody th", "rowheader");
    role(table, "td", "cell");
  });
})();

// Manager view / Full read switch on the scouting illustration.
// Without JavaScript the sheet stays in Manager view and the switch stays hidden.
(function () {
  var sheet = document.getElementById("scout");
  if (!sheet) return;
  var group = sheet.querySelector(".switch");
  if (!group) return;
  var buttons = group.querySelectorAll("button[data-set]");
  var status = document.getElementById("view-status");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

  function set(view) {
    if (sheet.getAttribute("data-view") === view) return;
    sheet.setAttribute("data-view", view);
    buttons.forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-set") === view));
    });
    var answer = sheet.querySelector(".answer-text.v-" + view);
    if (status && answer) status.textContent = answer.textContent.trim();
    if (reduce.matches) return;
    sheet.querySelectorAll(".v-" + view).forEach(function (el) {
      el.classList.remove("swap-in");
      void el.offsetWidth;
      el.classList.add("swap-in");
      el.addEventListener("animationend", function () { el.classList.remove("swap-in"); }, { once: true });
    });
  }

  buttons.forEach(function (b) {
    b.addEventListener("click", function () { set(b.getAttribute("data-set")); });
  });
  group.hidden = false;
})();

// Examples: a picker of real questions. The first plays when the block comes into view; picking
// another plays that one. The question types in, the assistant works, the data it read types into
// the sheet cell by cell, then the answer streams in word by word.
// Without JavaScript every sheet shows in full, one after another. Under reduced motion the picker
// still works and each sheet shows at once.
(function () {
  var host = document.querySelector(".ex-panels");
  var list = document.querySelector(".ex-tabs");
  if (!host || !list) return;
  var tabs = Array.from(list.querySelectorAll('[role="tab"]'));
  var panels = tabs.map(function (t) { return document.getElementById(t.getAttribute("aria-controls")); });
  if (panels.some(function (p) { return !p; })) return;
  var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window);

  // Wrap each character (or each word with its trailing space) of an element's text in a span.
  function split(el, unit) {
    var spans = [];
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      if (!node.nodeValue.trim() && unit === "c") return;
      var parts = unit === "c" ? Array.from(node.nodeValue) : node.nodeValue.match(/\S+\s*|\s+/g) || [];
      var frag = document.createDocumentFragment();
      parts.forEach(function (part) {
        var span = document.createElement("span");
        span.className = unit;
        span.textContent = part;
        frag.appendChild(span);
        spans.push(span);
      });
      node.parentNode.replaceChild(frag, node);
    });
    return spans;
  }

  // The data, in reading order: each table cell types in character by character; a cell holding a
  // drawn mark (an attribute bar, a stacked bar) appears whole and its bar grows.
  function within(root, selector) {
    var found = Array.from(root.querySelectorAll(selector));
    if (root.matches(selector)) found.unshift(root);
    return found;
  }
  function dataSteps(root) {
    var steps = [];
    root.querySelectorAll(".readout th, .readout td").forEach(function (cell) {
      if (cell.closest("caption")) return;
      if (cell.querySelector(".av, .stack")) { cell.classList.add("mark"); steps.push(cell); return; }
      split(cell, "c").forEach(function (span) { steps.push(span); });
    });
    // A drawn chart: each row, bar or card appears in turn and its bars grow.
    within(root, ".viz").forEach(function (fig) {
      fig.querySelectorAll(".beat").forEach(function (b) { steps.push(b); });
    });
    // A drawn move: the pitch appears, then each numbered step draws and its line of reasoning types in.
    within(root, ".move").forEach(function (fig) {
      var base = fig.querySelector("svg > .beat:not([data-step])");
      if (base) steps.push(base);
      fig.querySelectorAll(".move-key li").forEach(function (li) {
        var g = fig.querySelector('svg > .beat[data-step="' + li.getAttribute("data-step") + '"]');
        if (g) steps.push(g);
        split(li, "c").forEach(function (span) { steps.push(span); });
      });
      var src = fig.querySelector(".move-src");
      if (src) split(src, "c").forEach(function (span) { steps.push(span); });
    });
    return steps;
  }

  // Each sheet plays in its reading order: the answer's fields stream in as words, and the data or
  // drawing between them plays as data.
  var parts = panels.map(function (sheet) {
    if (still) return null;
    var blocks = [];
    Array.from(sheet.children).forEach(function (el) {
      if (el.matches(".sheet-head, .ask")) return;
      if (el.matches(".field")) {
        blocks.push({ words: Array.from(el.querySelectorAll(".call, .answer-text p, .answer-text li, .note")).map(function (p) { return split(p, "w"); }) });
      } else {
        blocks.push({ data: dataSteps(el) });
      }
    });
    return { chars: split(sheet.querySelector(".request"), "c"), blocks: blocks };
  });

  async function playData(steps, id) {
    // The data types into the sheet in about a second and a half whatever its size; a drawn step gets its own beat.
    var typed = steps.filter(function (el) { return !el.classList.contains("beat"); }).length;
    var per = Math.max(1, Math.ceil(typed / 90));
    for (var d = 0; d < steps.length;) {
      var el = steps[d];
      if (el.classList.contains("beat")) {
        el.classList.add("on");
        d++;
        await wait(el.closest(".viz") ? 230 : 520, id);
        continue;
      }
      var k = d;
      while (k < steps.length && k < d + per && !steps[k].classList.contains("beat")) steps[k++].classList.add("on");
      await wait(el.classList.contains("mark") ? 70 : 16, id);
      d = k;
    }
  }

  async function playWords(paragraphs, id) {
    for (var g = 0; g < paragraphs.length; g++) {
      for (var w = 0; w < paragraphs[g].length; w++) {
        paragraphs[g][w].classList.add("on");
        await wait(20, id);
      }
      await wait(140, id);
    }
  }

  var run = 0;
  function wait(ms, id) {
    return new Promise(function (resolve, reject) {
      setTimeout(function () { id === run ? resolve() : reject(); }, ms);
    });
  }

  async function play(i) {
    var id = ++run;
    var sheet = panels[i], p = parts[i];
    sheet.classList.remove("is-thinking");
    sheet.querySelectorAll(".on, .cur").forEach(function (el) { el.classList.remove("on", "cur"); });
    sheet.classList.add("play");
    sheet.setAttribute("aria-busy", "true");
    try {
      await wait(120, id);
      // The question types in: quick and a little uneven, with a beat after punctuation.
      var last = null;
      for (var c = 0; c < p.chars.length; c++) {
        if (last) last.classList.remove("cur");
        last = p.chars[c];
        last.classList.add("on", "cur");
        await wait(/[.,?:]/.test(last.textContent) ? 80 : 9 + Math.random() * 8, id);
      }
      await wait(220, id);
      last.classList.remove("cur");
      // The assistant works.
      sheet.classList.add("is-thinking");
      await wait(900, id);
      sheet.classList.remove("is-thinking");
      // Then the sheet in reading order: the answer streams in word by word, the figure draws.
      for (var b = 0; b < p.blocks.length; b++) {
        if (p.blocks[b].words) await playWords(p.blocks[b].words, id);
        else await playData(p.blocks[b].data, id);
        await wait(200, id);
      }
      finish(sheet);
    } catch (e) {
      finish(sheet);
    }
  }

  function finish(sheet) {
    sheet.classList.remove("play", "is-thinking");
    sheet.querySelectorAll(".cur").forEach(function (el) { el.classList.remove("cur"); });
    sheet.removeAttribute("aria-busy");
  }

  function select(i, focus) {
    tabs.forEach(function (t, n) {
      var on = n === i;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      panels[n].setAttribute("aria-hidden", String(!on));
      panels[n].inert = !on;
    });
    if (focus) tabs[i].focus();
    if (!still) play(i);
  }

  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () {
      if (t.getAttribute("aria-selected") !== "true") select(i, false);
    });
    t.addEventListener("keydown", function (e) {
      var to = { ArrowDown: i + 1, ArrowRight: i + 1, ArrowUp: i - 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
      if (to === undefined) return;
      e.preventDefault();
      select((to + tabs.length) % tabs.length, true);
    });
  });

  host.classList.add("picking");
  list.hidden = false;
  tabs.forEach(function (t, n) {
    panels[n].setAttribute("aria-hidden", String(n !== 0));
    panels[n].inert = n !== 0;
  });
  if (still) return;

  // Hold the first sheet blank until it comes into view, then play it.
  var first = panels[0];
  first.classList.add("play");
  var seen = new IntersectionObserver(function (entries) {
    if (!entries.some(function (e) { return e.isIntersecting; })) return;
    seen.disconnect();
    if (tabs[0].getAttribute("aria-selected") === "true" && run === 0) play(0);
  }, { rootMargin: "0px 0px -35% 0px" });
  seen.observe(first);
})();

// Copy buttons for the install line and the Steam launch line. Without the clipboard API the button stays hidden
// and the line can be selected by hand.
(function () {
  if (!navigator.clipboard) return;
  var status = document.getElementById("copy-status");
  document.querySelectorAll("button.copy[data-copy]").forEach(function (button) {
    var source = document.getElementById(button.getAttribute("data-copy"));
    if (!source) return;
    var timer;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(source.textContent.trim()).then(function () {
        button.textContent = "Copied";
        if (status) status.textContent = "Line copied.";
        clearTimeout(timer);
        timer = setTimeout(function () { button.textContent = "Copy"; }, 1600);
      }, function () {
        button.textContent = "Select it";
      });
    });
    button.hidden = false;
  });
})();
