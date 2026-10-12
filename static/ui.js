/* AutoCollab: shared table helpers (icon row actions, client-side pagination). */
window.UI = (() => {
  const svg = (paths) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  const ICONS = {
    edit: svg('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
    trash: svg('<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/>'),
    open: svg('<path d="M5 12h14M13 6l6 6-6 6"/>'),
    rerun: svg('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>'),
    stop: svg('<rect x="6" y="6" width="12" height="12" rx="2"/>'),
    revoke: svg('<circle cx="12" cy="12" r="9"/><path d="m5.7 5.7 12.6 12.6"/>'),
    prev: svg('<path d="m15 18-6-6 6-6"/>'),
    next: svg('<path d="m9 18 6-6-6-6"/>'),
    search: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
    play: svg('<path d="M7 4v16l13-8z"/>'),
    cards: svg('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'),
    list: svg('<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>'),
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // One icon button of a table row; `label` is its tooltip and accessible name.
  function action(act, label, icon, { danger = false, attrs = "" } = {}) {
    return `<button type="button" class="icon-btn${danger ? " danger" : ""}" data-act="${act}" title="${esc(label)}" aria-label="${esc(label)}" ${attrs}>${ICONS[icon]}</button>`;
  }
  const actions = (...buttons) => `<div class="row-actions">${buttons.filter(Boolean).join("")}</div>`;

  // --- pagination ------------------------------------------------------------
  const SIZES = [10, 25, 50];
  const state = {};

  function pageNumbers(page, pages) {
    if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
    const out = [1];
    const from = Math.max(2, page - 1), to = Math.min(pages - 1, page + 1);
    if (from > 2) out.push("…");
    for (let i = from; i <= to; i++) out.push(i);
    if (to < pages - 1) out.push("…");
    out.push(pages);
    return out;
  }

  // Renders `table(rows)` for the current page of `list` into the element `wrap`,
  // with the pager just after it. `rerender` is called again when the page changes.
  function paginate(wrap, list, table, rerender, size = 10, sizes = SIZES) {
    const st = page(wrap.id, size, sizes);
    st.rerender = rerender;
    const total = list.length, pages = Math.max(1, Math.ceil(total / st.size));
    st.page = Math.min(Math.max(1, st.page), pages);
    const start = (st.page - 1) * st.size;
    wrap.innerHTML = total ? table(list.slice(start, start + st.size)) : "";
    renderPager(wrap, st, total);
  }

  // The current page of a list paged by the server: read it to build the request.
  function page(id, size = 10, sizes = SIZES) {
    const st = state[id] ||= { page: 1, size, sizes };
    if (st.sizes.join() !== sizes.join()) {  // switched between cards and list: their page sizes differ
      st.sizes = sizes; st.size = size; st.page = 1;
    }
    return st;
  }

  // Pager for a page the server already cut out (`total` = all matching rows); `reload` fetches again.
  function remote(wrap, total, reload) {
    const st = page(wrap.id);
    st.rerender = reload;
    renderPager(wrap, st, total);
  }

  function renderPager(wrap, st, total) {
    const pages = Math.max(1, Math.ceil(total / st.size)), start = (st.page - 1) * st.size;
    let pager = wrap.nextElementSibling?.classList.contains("pager") ? wrap.nextElementSibling : null;
    if (total <= st.sizes[0]) { pager?.remove(); return; }
    if (!pager) { pager = document.createElement("div"); pager.className = "pager"; pager.dataset.for = wrap.id; wrap.after(pager); }
    pager.innerHTML = `<span>${start + 1}–${Math.min(start + st.size, total)} sur ${total}</span>
      <div class="pager-nav">
        <label class="hint size-label" style="display: inline-flex; align-items: center; gap: 6px; margin-right: 8px">Lignes par page
          <select data-size>${st.sizes.map(n => `<option ${n === st.size ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        <button type="button" class="icon-btn" data-pg="${st.page - 1}" ${st.page === 1 ? "disabled" : ""} aria-label="Page précédente" title="Page précédente">${ICONS.prev}</button>
        ${pageNumbers(st.page, pages).map(n => n === "…" ? '<span class="gap">…</span>'
          : `<button type="button" class="pg" data-pg="${n}" ${n === st.page ? 'aria-current="page"' : ""} aria-label="Page ${n}">${n}</button>`).join("")}
        <button type="button" class="icon-btn" data-pg="${st.page + 1}" ${st.page === pages ? "disabled" : ""} aria-label="Page suivante" title="Page suivante">${ICONS.next}</button>
      </div>`;
  }

  // Back to page 1 (after a search or a filter change).
  function resetPage(id) { if (state[id]) state[id].page = 1; }

  document.addEventListener("click", (e) => {
    const b = e.target.closest(".pager [data-pg]");
    if (!b || b.disabled) return;
    const st = state[b.closest(".pager").dataset.for];
    if (!st) return;
    st.page = Number(b.dataset.pg); st.rerender();
  });
  document.addEventListener("change", (e) => {
    const sel = e.target.closest(".pager [data-size]");
    if (!sel) return;
    const st = state[sel.closest(".pager").dataset.for];
    if (!st) return;
    st.size = Number(sel.value); st.page = 1; st.rerender();
  });

  // Close button (×) in the top-right corner of every dialog. It goes through the "cancel"
  // event like Escape, so a dialog that refuses Escape (forced password change) stays open.
  function addCloseButtons() {
    document.querySelectorAll("dialog").forEach(dlg => {
      if (dlg.querySelector(":scope > .dialog-x")) return;
      const b = document.createElement("button");
      b.type = "button"; b.className = "dialog-x"; b.title = "Fermer"; b.setAttribute("aria-label", "Fermer");
      b.innerHTML = svg('<path d="M18 6 6 18M6 6l12 12"/>');
      b.onclick = () => { if (dlg.dispatchEvent(new Event("cancel", { cancelable: true }))) dlg.close(); };
      dlg.prepend(b);
    });
  }
  // Field help in dialogs: the grey text under a field becomes an (i) next to its label,
  // shown on hover or focus. A hint that introduces what follows it (e.g. the variables) stays.
  const INFO_ICON = svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>');
  function tipButton(text) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "tip"; b.setAttribute("aria-label", text.trim());
    b.innerHTML = INFO_ICON;
    return b;
  }
  function addInfoTips() {
    document.querySelectorAll("dialog .field > .hint:last-child").forEach(hint => {
      const label = hint.parentElement.querySelector(":scope > label, :scope > .field-label");
      if (!label) return;
      label.append(tipButton(hint.textContent));
      hint.remove();
    });
    document.querySelectorAll("dialog .check strong + br + .hint").forEach(hint => {
      hint.previousElementSibling.previousElementSibling.after(tipButton(hint.textContent));
      hint.previousElementSibling.remove(); // the <br>
      hint.remove();
    });
  }
  function boot() { addCloseButtons(); addInfoTips(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  // One floating bubble for every (i): read from aria-label (translated by i18n.js), placed
  // inside the open dialog so it shows above the backdrop, clamped to the window.
  let pop = null;
  function showTip(el) {
    if (!pop) { pop = document.createElement("div"); pop.className = "tip-pop"; pop.setAttribute("role", "tooltip"); }
    (el.closest("dialog") || document.body).append(pop);
    pop.textContent = el.getAttribute("aria-label");
    pop.hidden = false;
    const r = el.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    const left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8);
    const below = r.bottom + 8 + h < innerHeight;
    pop.style.left = `${left}px`;
    pop.style.top = `${below ? r.bottom + 8 : r.top - h - 8}px`;
  }
  const hideTip = () => { if (pop) pop.hidden = true; };
  document.addEventListener("mouseover", (e) => { const t = e.target.closest(".tip"); if (t) showTip(t); });
  document.addEventListener("mouseout", (e) => { if (e.target.closest(".tip")) hideTip(); });
  document.addEventListener("focusin", (e) => { const t = e.target.closest(".tip"); if (t) showTip(t); else hideTip(); });
  document.addEventListener("focusout", (e) => { if (e.target.closest(".tip")) hideTip(); });
  document.addEventListener("close", hideTip, true);

  // --- loading feedback ---------------------------------------------------------
  // Only for what the person asked for (page load, click, form, navigation): the background
  // refreshes (runs list, live screen...) stay silent, or the bar would blink all the time.
  const INTENT_MS = 1500;
  let lastIntent = performance.now(), lastButton = null, pending = 0, barTimer = null;
  const note = (e) => {
    lastIntent = performance.now();
    const b = e.type === "submit" ? e.submitter : e.target?.closest?.(".btn, .icon-btn, button");
    if (b || (e.type !== "keydown" && e.type !== "submit")) lastButton = b || null;
  };
  for (const type of ["click", "submit", "hashchange", "popstate", "keydown"]) addEventListener(type, note, true);

  const bar = document.createElement("div");
  bar.className = "top-progress"; bar.setAttribute("role", "progressbar"); bar.setAttribute("aria-label", "Chargement");
  const mount = () => document.body.appendChild(bar);
  document.body ? mount() : addEventListener("DOMContentLoaded", mount);

  function begin() {
    if (pending++ === 0) {
      document.documentElement.classList.add("is-loading");
      clearTimeout(barTimer);
      barTimer = setTimeout(() => bar.classList.add("on"), 150);  // quick answers don't flash
    }
  }
  function end() {
    if (--pending === 0) {
      document.documentElement.classList.remove("is-loading");
      clearTimeout(barTimer);
      bar.classList.remove("on");
    }
  }

  // Wraps a request: progress bar, and a spinner on the button that started it.
  function track(promise) {
    if (performance.now() - lastIntent > INTENT_MS) return promise;
    const button = lastButton && lastButton.isConnected ? lastButton : null;
    begin();
    if (button) button.dataset.busy = String(Number(button.dataset.busy || 0) + 1), button.setAttribute("aria-busy", "true");
    const done = () => {
      end();
      if (button) {
        const left = Number(button.dataset.busy || 1) - 1;
        if (left > 0) button.dataset.busy = String(left);
        else { delete button.dataset.busy; button.removeAttribute("aria-busy"); }
      }
    };
    promise.then(done, done);
    return promise;
  }

  // --- information window ---------------------------------------------------------
  // For "you need to do X first" messages: a short explanation and the action that helps,
  // instead of a red toast that looks like an error and disappears.
  // UI.notice({ title, text, action: { label, run } })
  let noticeDlg = null;
  function notice({ title, text, action }) {
    if (!noticeDlg) {
      noticeDlg = document.createElement("dialog");
      noticeDlg.className = "notice-dlg";
      noticeDlg.setAttribute("aria-labelledby", "noticeTitle");
      noticeDlg.innerHTML = `<h2 id="noticeTitle"></h2>
        <div class="dialog-body"><div class="notice-row"><span class="notice-icon">${svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>')}</span><p id="noticeText"></p></div></div>
        <div class="dialog-foot"><button type="button" class="btn btn-primary" id="noticeAction"></button><button type="button" class="btn btn-outline" id="noticeClose">Fermer</button></div>`;
      document.body.append(noticeDlg);
      addCloseButtons();
      noticeDlg.querySelector("#noticeClose").onclick = () => noticeDlg.close();
    }
    noticeDlg.querySelector("#noticeTitle").textContent = title;
    noticeDlg.querySelector("#noticeText").textContent = text;
    const btn = noticeDlg.querySelector("#noticeAction");
    btn.hidden = !action;
    if (action) { btn.textContent = action.label; btn.onclick = () => { noticeDlg.close(); action.run(); }; }
    noticeDlg.showModal();
    (action ? btn : noticeDlg.querySelector("#noticeClose")).focus();
  }

  // --- drop-down lists ------------------------------------------------------------
  // The browser's own <select> menu can't be styled. Each one gets a button + list in the
  // app's look; the real <select> stays in the page, hidden and kept in sync, so the code
  // keeps reading .value and listening to "change" as before. Selects added later (toolbars,
  // chain steps, pagers) are picked up by an observer.
  const CHEVRON = svg('<path d="m6 9 6 6 6-6"/>'), CHECK = svg('<path d="M20 6 9 17l-5-5"/>');
  const valueDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  const indexDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "selectedIndex");
  let openDd = null, ddSeq = 0;

  function enhanceSelect(sel) {
    if (sel.dataset.dd || sel.multiple || sel.classList.contains("native")) return;
    sel.dataset.dd = "1";
    const id = `dd${++ddSeq}`;
    const wrap = document.createElement("span");
    wrap.className = `dd ${sel.classList.contains("select") ? "dd-block" : ""}`;
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = `dd-btn ${sel.className}`;
    btn.setAttribute("aria-haspopup", "listbox"); btn.setAttribute("aria-expanded", "false");
    btn.innerHTML = `<span class="dd-value" id="${id}v"></span>${CHEVRON}`;
    const list = document.createElement("div");
    list.className = "dd-list"; list.id = `${id}l`; list.setAttribute("role", "listbox"); list.tabIndex = -1; list.hidden = true;
    btn.setAttribute("aria-controls", list.id);
    sel.before(wrap);
    wrap.append(sel, btn, list);
    sel.classList.add("dd-native"); sel.tabIndex = -1; sel.setAttribute("aria-hidden", "true");

    // Accessible name: the select's aria-label, or its <label for>, followed by the value.
    const label = sel.id && document.querySelector(`label[for="${sel.id}"]`);
    if (label) { label.id ||= `${id}lab`; btn.setAttribute("aria-labelledby", `${label.id} ${id}v`); label.addEventListener("click", (e) => { e.preventDefault(); btn.focus(); }); }

    const options = () => [...sel.options];
    function refresh() {
      const opts = options(), cur = sel.selectedIndex;
      // Every label stacked in one grid cell: the button is as wide as the longest option.
      btn.querySelector(".dd-value").innerHTML = opts.map((o, i) => `<span ${i === cur ? "" : 'class="dd-ghost" aria-hidden="true"'}>${esc(o.textContent)}</span>`).join("") || "<span></span>";
      if (sel.getAttribute("aria-label") && !label) btn.setAttribute("aria-label", `${sel.getAttribute("aria-label")} : ${opts[cur]?.textContent || ""}`);
      btn.disabled = sel.disabled;
      wrap.hidden = sel.hidden;
      if (!list.hidden) renderList();
    }
    function renderList(active = sel.selectedIndex) {
      list.innerHTML = options().map((o, i) => `<div class="dd-opt" role="option" id="${id}o${i}" data-i="${i}" aria-selected="${i === sel.selectedIndex}" ${o.disabled ? 'aria-disabled="true"' : ""}>${CHECK}<span>${esc(o.textContent)}</span></div>`).join("");
      setActive(active);
    }
    function setActive(i) {
      list.querySelectorAll(".dd-opt.active").forEach(o => o.classList.remove("active"));
      const el = list.querySelector(`[data-i="${i}"]`);
      if (!el) { list.removeAttribute("aria-activedescendant"); return; }
      el.classList.add("active"); list.setAttribute("aria-activedescendant", el.id);
      el.scrollIntoView({ block: "nearest" });
    }
    const activeIndex = () => Number(list.querySelector(".dd-opt.active")?.dataset.i ?? sel.selectedIndex);
    function place() {
      const r = btn.getBoundingClientRect();
      list.style.minWidth = `${r.width}px`;
      const h = Math.min(list.scrollHeight, 300), below = innerHeight - r.bottom - 8;
      list.style.left = `${Math.min(r.left, innerWidth - list.offsetWidth - 8)}px`;
      list.style.top = `${below >= h || below >= r.top ? r.bottom + 4 : r.top - 4 - h}px`;
    }
    function open() {
      if (openDd && openDd !== api) openDd.close(false);
      renderList(); list.hidden = false; place();
      btn.setAttribute("aria-expanded", "true"); wrap.classList.add("open");
      openDd = api; list.focus();
    }
    function close(focus = true) {
      list.hidden = true; btn.setAttribute("aria-expanded", "false"); wrap.classList.remove("open");
      if (openDd === api) openDd = null;
      if (focus) btn.focus();
    }
    function choose(i) {
      const o = sel.options[i];
      if (!o || o.disabled) return;
      const changed = sel.selectedIndex !== i;
      indexDesc.set.call(sel, i);
      refresh(); close();
      if (changed) { sel.dispatchEvent(new Event("input", { bubbles: true })); sel.dispatchEvent(new Event("change", { bubbles: true })); }
    }
    const api = { close, place, wrap };

    btn.addEventListener("click", () => list.hidden ? open() : close());
    btn.addEventListener("keydown", (e) => {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); open(); }
    });
    list.addEventListener("click", (e) => { const o = e.target.closest(".dd-opt"); if (o) choose(Number(o.dataset.i)); });
    list.addEventListener("mousemove", (e) => { const o = e.target.closest(".dd-opt"); if (o && !o.classList.contains("active")) setActive(Number(o.dataset.i)); });
    let typed = "", typedTimer = null;
    list.addEventListener("keydown", (e) => {
      const n = sel.options.length, i = activeIndex();
      const move = (to) => { e.preventDefault(); setActive(Math.max(0, Math.min(n - 1, to))); };
      if (e.key === "ArrowDown") return move(i + 1);
      if (e.key === "ArrowUp") return move(i - 1);
      if (e.key === "Home") return move(0);
      if (e.key === "End") return move(n - 1);
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); return choose(i); }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); return close(); }  // keeps the dialog open
      if (e.key === "Tab") return close(false);
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
        typed += e.key.toLowerCase(); clearTimeout(typedTimer); typedTimer = setTimeout(() => typed = "", 700);
        const hit = options().findIndex(o => o.textContent.trim().toLowerCase().replace(/^trier : /, "").startsWith(typed));
        if (hit >= 0) move(hit);
      }
    });
    list.addEventListener("focusout", (e) => { if (!wrap.contains(e.relatedTarget)) close(false); });
    sel.addEventListener("focus", () => btn.focus());
    sel.addEventListener("change", refresh);

    // Code that sets .value / .selectedIndex directly, or rebuilds the options, updates the button too.
    Object.defineProperty(sel, "value", { configurable: true, get() { return valueDesc.get.call(this); }, set(v) { valueDesc.set.call(this, v); refresh(); } });
    Object.defineProperty(sel, "selectedIndex", { configurable: true, get() { return indexDesc.get.call(this); }, set(v) { indexDesc.set.call(this, v); refresh(); } });
    new MutationObserver(refresh).observe(sel, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["hidden", "disabled", "selected"] });
    refresh();
  }

  const enhanceAll = (root) => root.querySelectorAll?.("select").forEach(enhanceSelect);
  function startSelects() {
    enhanceAll(document);
    new MutationObserver((records) => {
      for (const r of records) for (const node of r.addedNodes) {
        if (node.nodeType !== 1) continue;
        if (node.tagName === "SELECT") enhanceSelect(node); else enhanceAll(node);
      }
    }).observe(document.body, { childList: true, subtree: true });
  }
  document.readyState === "loading" ? addEventListener("DOMContentLoaded", startSelects) : startSelects();
  document.addEventListener("pointerdown", (e) => { if (openDd && !openDd.wrap.contains(e.target)) openDd.close(false); }, true);
  addEventListener("resize", () => openDd?.close(false));
  addEventListener("scroll", (e) => { if (openDd && !e.target.closest?.(".dd-list")) openDd.place(); }, true);

  return { ICONS, action, actions, notice, paginate, page, remote, resetPage, track };
})();
