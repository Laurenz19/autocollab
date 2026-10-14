/* AutoCollab: the assistant's side panel, on every page (app/assistant.py on the server).

Read only: it answers questions and drafts agents. A draft (```agent block) opens the "Nouvel agent"
form pre-filled, through window.openAgentDraft on the main page, or sessionStorage + /#/agents
from the other pages; the person saves it themselves. Conversations are stored on the server.
*/
(() => {
  const OPEN_KEY = "ac_asst_open", CONV_KEY = "ac_asst_conv", MODEL_KEY = "ac_asst_model";
  const svg = (paths) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  const ICONS = {
    spark: svg('<path d="M12 3l1.8 4.9L19 9.7l-5.2 1.8L12 16.5l-1.8-5L5 9.7l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>'),
    close: svg('<path d="M18 6 6 18M6 6l12 12"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    history: svg('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>'),
    send: svg('<path d="M5 12h14M13 6l6 6-6 6"/>'),
    stop: svg('<rect x="7" y="7" width="10" height="10" rx="1.5"/>'),
    trash: svg('<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>'),
    back: svg('<path d="m15 18-6-6 6-6"/>'),
  };
  const TOOL_LABELS = {
    get_documentation: "Lecture de la documentation", list_agents: "Consultation de vos agents",
    list_variables: "Lecture des variables", list_templates: "Lecture des modèles d'agents", list_runs: "Consultation de vos exécutions", get_run: "Lecture d'une exécution",
    list_chains: "Consultation de vos chaînes", get_chain_run: "Lecture d'une exécution de chaîne",
    get_context: "Lecture du contexte", preview_context: "Aperçu du contexte",
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
  };

  // --- Markdown (the small subset the assistant is asked to write), always escaped first ---------

  function inline(text) {
    return esc(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
        const href = url.replace(/&amp;/g, "&");
        if (!/^(\/|#|https?:\/\/)/.test(href)) return label;
        const ext = /^https?:/.test(href) ? ' target="_blank" rel="noopener noreferrer"' : "";
        return `<a href="${esc(href)}"${ext}>${label}</a>`;
      });
  }

  function draftCard(code, closed) {
    let d = null;
    try { d = JSON.parse(code); } catch {}
    if (!d || typeof d !== "object" || !d.instructions) {
      return closed ? `<pre><code>${esc(code)}</code></pre>` : `<div class="asst-draft pending">Rédaction de l'agent…</div>`;
    }
    const domains = Array.isArray(d.allowed_domains) ? d.allowed_domains.filter(Boolean) : [];
    return `<div class="asst-draft" data-draft="${esc(JSON.stringify(d))}">
      <div class="asst-draft-head"><span class="asst-draft-tag">Projet d'agent</span><strong>${esc(d.name || "Sans nom")}</strong></div>
      <div class="asst-draft-text">${esc(d.instructions)}</div>
      <div class="asst-draft-meta">${domains.length ? `Sites : ${esc(domains.join(", "))}` : "Tous les sites"}${d.approval_mode ? " · avec validation" : ""}</div>
      <div class="asst-draft-actions">
        <button type="button" class="btn btn-primary btn-sm" data-act="draft">Ouvrir dans le formulaire</button>
        <button type="button" class="btn btn-text btn-sm" data-act="copy-draft">Copier la consigne</button>
      </div>
    </div>`;
  }

  function md(src) {
    const blocks = [];
    src = src.replace(/```([\w-]*)[^\n]*\n?([\s\S]*?)(```|$)/g, (m, lang, code, end) => {
      blocks.push({ lang: lang.toLowerCase(), code: code.replace(/\n$/, ""), closed: !!end });
      return `\n\u0000${blocks.length - 1}\u0000\n`;
    });
    const out = [];
    let list = null, para = [];
    const flushPara = () => { if (para.length) { out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; } };
    const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map(i => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; } };
    for (const line of src.split("\n")) {
      const block = line.match(/^\u0000(\d+)\u0000$/);
      const bullet = line.match(/^\s*[-*•]\s+(.*)$/), num = line.match(/^\s*\d+[.)]\s+(.*)$/), head = line.match(/^#{1,4}\s+(.*)$/);
      if (block) {
        flushPara(); flushList();
        const b = blocks[+block[1]];
        out.push(b.lang === "agent" ? draftCard(b.code, b.closed)
          : `<div class="asst-code"><pre><code>${esc(b.code)}</code></pre><button type="button" class="asst-copy" data-act="copy">Copier</button></div>`);
      } else if (bullet || num) {
        flushPara();
        const tag = bullet ? "ul" : "ol";
        if (list && list.tag !== tag) flushList();
        (list ||= { tag, items: [] }).items.push((bullet || num)[1]);
      } else if (head) {
        flushPara(); flushList(); out.push(`<p class="asst-h">${inline(head[1])}</p>`);
      } else if (!line.trim()) {
        flushPara(); flushList();
      } else {
        flushList(); para.push(line);
      }
    }
    flushPara(); flushList();
    return out.join("");
  }

  // --- panel -------------------------------------------------------------------------------

  const fab = document.createElement("button");
  fab.type = "button"; fab.className = "asst-fab"; fab.innerHTML = ICONS.spark + "<span>Assistant</span>";
  fab.setAttribute("aria-label", "Ouvrir l'assistant"); fab.title = "Assistant";

  const panel = document.createElement("aside");
  panel.className = "asst"; panel.hidden = true; panel.setAttribute("aria-label", "Assistant");
  panel.innerHTML = `
    <header class="asst-head">
      <button type="button" class="icon-btn" data-act="back" aria-label="Retour à la conversation" title="Retour" hidden>${ICONS.back}</button>
      <span class="asst-title">${ICONS.spark}<strong>Assistant</strong></span>
      <button type="button" class="icon-btn" data-act="history" aria-label="Conversations précédentes" title="Conversations précédentes">${ICONS.history}</button>
      <button type="button" class="icon-btn" data-act="new" aria-label="Nouvelle conversation" title="Nouvelle conversation">${ICONS.plus}</button>
      <button type="button" class="icon-btn" data-act="close" aria-label="Fermer l'assistant" title="Fermer">${ICONS.close}</button>
    </header>
    <div class="asst-body" id="asstBody"></div>
    <div class="asst-list" id="asstList" hidden></div>
    <form class="asst-foot" id="asstForm">
      <textarea id="asstInput" rows="1" maxlength="4000" placeholder="Posez votre question…" aria-label="Votre message"></textarea>
      <div class="asst-actions">
        <select class="asst-model" id="asstModel" aria-label="Modèle d'IA de l'assistant" hidden></select>
        <button type="submit" class="asst-send" id="asstSend" aria-label="Envoyer" title="Envoyer (Entrée)">${ICONS.send}</button>
      </div>
    </form>
    <p class="asst-note">Lecture seule : l'assistant consulte vos agents, exécutions et contexte, mais ne lance et ne modifie rien.</p>
    <span class="sr-only" aria-live="polite" id="asstStatus"></span>`;

  const $ = (sel) => panel.querySelector(sel);
  const body = $("#asstBody"), listEl = $("#asstList"), input = $("#asstInput"), sendBtn = $("#asstSend"), modelSel = $("#asstModel");
  let convId = store.get(CONV_KEY), messages = [], controller = null, loaded = false;

  function suggestions() {
    const run = location.pathname === "/" && location.hash.match(/^#\/executions\/([\w-]+)/);
    const items = [
      run && "Pourquoi cette exécution n'a-t-elle pas abouti ?",
      "Aide-moi à rédiger un agent qui télécharge les relevés bancaires du mois précédent",
      "Quelles exécutions ont échoué récemment ?",
      "Comment fonctionnent les chaînes d'agents ?",
    ].filter(Boolean);
    return `<div class="asst-empty">
      <span class="asst-empty-mark">${ICONS.spark}</span>
      <p><strong>Comment puis-je vous aider ?</strong></p>
      <p>Questions sur AutoCollab, explication d'une exécution, rédaction d'un agent.</p>
      <div class="asst-sugg">${items.map(s => `<button type="button" data-act="ask" data-q="${esc(s)}">${esc(s)}</button>`).join("")}</div>
    </div>`;
  }

  function messageHtml(m) {
    if (m.role === "user") return `<div class="asst-msg user"><div class="asst-bubble">${esc(m.content)}</div></div>`;
    const tools = (m.tools || []).length ? `<div class="asst-tools">${[...new Set(m.tools)].map(t => `<span>${esc(TOOL_LABELS[t] || t)}</span>`).join("")}</div>` : "";
    const working = m.pending && !m.content ? `<div class="asst-typing" aria-hidden="true"><i></i><i></i><i></i></div>` : "";
    const error = m.error ? `<p class="asst-error">${esc(m.error)}</p>` : "";
    return `<div class="asst-msg bot">${tools}<div class="asst-md">${md(m.content || "")}</div>${working}${error}</div>`;
  }

  function render() {
    const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    body.innerHTML = messages.length ? messages.map(messageHtml).join("") : suggestions();
    if (nearBottom || controller) body.scrollTop = body.scrollHeight;
    sendBtn.innerHTML = controller ? ICONS.stop : ICONS.send;
    sendBtn.setAttribute("aria-label", controller ? "Arrêter la réponse" : "Envoyer");
    sendBtn.title = controller ? "Arrêter" : "Envoyer (Entrée)";
  }
  let frame = 0;
  const renderSoon = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; render(); }); };

  async function request(path, opts = {}) {
    const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    if (r.status === 401) { location.replace("/login"); throw new Error("Session expirée"); }
    if (!r.ok) {
      let d = r.statusText; try { d = (await r.json()).detail || d; } catch {}
      throw new Error(Array.isArray(d) ? "Message vide ou trop long." : d);
    }
    return r;
  }

  // Model picker: the models of the providers that have a key (GET /api/assistant/models), the
  // Administration's choice first. The person's choice is remembered on this browser.
  let models = [];
  async function loadModels() {
    try { models = await (await request("/api/assistant/models")).json(); } catch { models = []; }
    const saved = store.get(MODEL_KEY);
    const groups = [...new Set(models.map(m => m.provider_label))];
    modelSel.innerHTML = groups.map(g => `<optgroup label="${esc(g)}">${models.map((m, i) => m.provider_label !== g ? "" :
      `<option value="${i}">${esc(m.model)}${m.default ? " (par défaut)" : ""}</option>`).join("")}</optgroup>`).join("");
    const pick = models.findIndex(m => `${m.provider}|${m.model}` === saved);
    modelSel.value = String(pick >= 0 ? pick : 0);
    modelSel.hidden = models.length < 2;  // nothing to choose with a single model
    modelSel.title = models[+modelSel.value] ? `${models[+modelSel.value].provider_label} · ${models[+modelSel.value].model}` : "";
  }
  modelSel.addEventListener("change", () => {
    const m = models[+modelSel.value];
    if (!m) return;
    store.set(MODEL_KEY, m.default ? null : `${m.provider}|${m.model}`);
    modelSel.title = `${m.provider_label} · ${m.model}`;
  });
  const chosenModel = () => { const m = models[+modelSel.value]; return m && !m.default ? { provider: m.provider, model: m.model } : {}; };

  async function loadConversation(id) {
    try {
      const c = await (await request(`/api/assistant/conversations/${encodeURIComponent(id)}`)).json();
      convId = c.id; messages = c.messages;
    } catch { convId = null; messages = []; }
    store.set(CONV_KEY, convId);
    render();
  }

  function newConversation() {
    if (controller) controller.abort();
    convId = null; messages = []; store.set(CONV_KEY, null);
    showList(false); render(); input.focus();
  }

  async function showList(on) {
    listEl.hidden = !on; body.hidden = on;
    $('[data-act="back"]').hidden = !on; $('[data-act="history"]').hidden = on;
    if (!on) return;
    listEl.innerHTML = `<p class="asst-list-empty">Chargement…</p>`;
    try {
      const list = await (await request("/api/assistant/conversations")).json();
      listEl.innerHTML = list.length ? list.map(c => `
        <div class="asst-conv${c.id === convId ? " current" : ""}">
          <button type="button" class="asst-conv-open" data-act="open" data-id="${esc(c.id)}"><span>${esc(c.title)}</span><time>${esc(when(c.updated_at))}</time></button>
          <button type="button" class="icon-btn danger" data-act="delete" data-id="${esc(c.id)}" aria-label="Supprimer la conversation" title="Supprimer">${ICONS.trash}</button>
        </div>`).join("") : `<p class="asst-list-empty">Aucune conversation pour l'instant.</p>`;
    } catch (e) { listEl.innerHTML = `<p class="asst-error">${esc(e.message)}</p>`; }
  }
  function when(t) {
    const d = new Date(t); if (isNaN(d)) return "";
    const today = new Date().toDateString() === d.toDateString();
    return today ? d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
  }

  async function send(text) {
    text = text.trim();
    if (!text || controller) return;
    input.value = ""; autosize();
    const reply = { role: "assistant", content: "", tools: [], pending: true };
    messages.push({ role: "user", content: text }, reply);
    controller = new AbortController();
    render();
    $("#asstStatus").textContent = "L'assistant répond…";
    try {
      const r = await request("/api/assistant/chat", {
        method: "POST", signal: controller.signal,
        body: JSON.stringify({ message: text, conversation_id: convId, page: (location.pathname + location.hash).slice(0, 200), lang: window.I18N ? I18N.lang : "fr", ...chosenModel() }),
      });
      const reader = r.body.getReader(), decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buffer.indexOf("\n\n")) >= 0) {
          const chunk = buffer.slice(0, cut); buffer = buffer.slice(cut + 2);
          const kind = (chunk.match(/^event: (.*)$/m) || [])[1], raw = (chunk.match(/^data: (.*)$/m) || [])[1];
          if (!kind || raw == null) continue;
          const data = JSON.parse(raw);
          if (kind === "conversation") { convId = data.id; store.set(CONV_KEY, convId); }
          else if (kind === "delta") reply.content += data.text;
          else if (kind === "tool") reply.tools.push(data.name);
          else if (kind === "error") reply.error = data.message;
          renderSoon();
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") reply.error = e.message;
      else if (reply.content) reply.content += "\n\n*(réponse interrompue)*";
    }
    reply.pending = false; controller = null;
    if (!reply.content && !reply.error) reply.error = "Pas de réponse.";
    $("#asstStatus").textContent = "Réponse terminée.";
    render();
    input.focus();
  }

  function openDraft(d) {
    const draft = {
      name: String(d.name || "").slice(0, 80), instructions: String(d.instructions || ""),
      allowed_domains: Array.isArray(d.allowed_domains) ? d.allowed_domains.map(String) : [],
      approval_mode: !!d.approval_mode, max_steps: Number.isInteger(d.max_steps) ? d.max_steps : null,
    };
    if (typeof window.openAgentDraft === "function") { window.openAgentDraft(draft); return; }
    try { sessionStorage.setItem("ac_agent_draft", JSON.stringify(draft)); } catch {}
    location.href = "/#/agents";
  }

  async function copy(text, btn) {
    try { await navigator.clipboard.writeText(text); const old = btn.textContent; btn.textContent = "Copié"; setTimeout(() => btn.textContent = old, 1500); } catch {}
  }

  function setOpen(on) {
    panel.hidden = !on; fab.hidden = on;
    document.documentElement.classList.toggle("asst-open", on);
    store.set(OPEN_KEY, on ? "1" : null);
    if (on) {
      if (!loaded) { loaded = true; if (convId) loadConversation(convId); else render(); }
      loadModels();  // each time: a key may have been added or removed in Administration
      setTimeout(() => input.focus(), 0);
    } else fab.focus();
  }

  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; }

  panel.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === "close") setOpen(false);
    else if (act === "new") newConversation();
    else if (act === "history") showList(true);
    else if (act === "back") showList(false);
    else if (act === "ask") send(btn.dataset.q);
    else if (act === "open") { showList(false); await loadConversation(btn.dataset.id); }
    else if (act === "delete") {
      if (!confirm("Supprimer cette conversation ?")) return;
      try {
        await request(`/api/assistant/conversations/${encodeURIComponent(btn.dataset.id)}`, { method: "DELETE" });
        if (btn.dataset.id === convId) { convId = null; messages = []; store.set(CONV_KEY, null); render(); }
        showList(true);
      } catch (err) { alert(err.message); }
    }
    else if (act === "copy") copy(btn.parentElement.querySelector("code").textContent, btn);
    else if (act === "draft" || act === "copy-draft") {
      const d = JSON.parse(btn.closest(".asst-draft").dataset.draft);
      if (act === "draft") openDraft(d); else copy(d.instructions, btn);
    }
  });
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape" && !e.defaultPrevented) setOpen(false); });
  $("#asstForm").addEventListener("submit", (e) => { e.preventDefault(); if (controller) controller.abort(); else send(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!controller) send(input.value); }
  });
  input.addEventListener("input", autosize);
  fab.addEventListener("click", () => setOpen(true));

  function mount() {
    document.body.append(fab, panel);
    if (store.get(OPEN_KEY) === "1") setOpen(true);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
})();
