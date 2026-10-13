/**
 * Ask the MBR — a chat panel on the MBR page (Jonny only, Oct 2026).
 *
 * The server decides who has it (can_chat on the MBR response); this file only
 * draws the button and panel. Opening the panel asks the server to build the
 * figures straight away, so the first question doesn't wait for them. The
 * conversation lives in this tab only (sessionStorage) and goes up whole with
 * each question; nothing is stored on the server.
 */
(function () {
  const KEY = "mbr-chat";
  let year = null, history = [], busy = false, built = false;

  try { history = JSON.parse(sessionStorage.getItem(KEY) || "[]"); } catch (_) { history = []; }
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(history)); } catch (_) {} };

  const esc = s => String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Just enough Markdown for an analyst's answer: paragraphs, bullets, bold
  function format(text) {
    const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    const out = [];
    let list = null;
    const flush = () => { if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; } };
    for (const raw of String(text).split("\n")) {
      const line = raw.trim();
      const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (bullet) { (list = list || []).push(`<li>${inline(bullet[1])}</li>`); continue; }
      flush();
      if (!line) continue;
      const head = line.match(/^#{1,6}\s+(.*)$/);
      out.push(head ? `<p><strong>${inline(head[1])}</strong></p>` : `<p>${inline(line)}</p>`);
    }
    flush();
    return out.join("");
  }

  function build() {
    if (built) return;
    built = true;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mchat-open";
    btn.textContent = "Ask the MBR";
    document.body.appendChild(btn);

    const panel = document.createElement("aside");
    panel.className = "mchat";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="mchat-head">
        <div><div class="mchat-title">Ask the MBR</div>
          <div class="mchat-sub">Both London desks, every month and consultant</div></div>
        <div class="mchat-actions">
          <button type="button" class="mchat-link" data-act="clear">New chat</button>
          <button type="button" class="mchat-x" data-act="close" aria-label="Close">×</button>
        </div>
      </div>
      <div class="mchat-log" aria-live="polite"></div>
      <form class="mchat-form">
        <textarea rows="2" maxlength="2000" placeholder="e.g. Who's carrying the book this quarter?"></textarea>
        <button type="submit" class="save-btn">Ask</button>
      </form>`;
    document.body.appendChild(panel);

    const log = panel.querySelector(".mchat-log");
    const box = panel.querySelector("textarea");
    const form = panel.querySelector("form");

    function draw() {
      log.innerHTML = history.length ? history.map(m =>
        `<div class="mchat-msg ${m.role}">${m.role === "user" ? `<p>${esc(m.content)}</p>` : format(m.content)}</div>`
      ).join("") : `<p class="mchat-hint">Ask about the numbers on either desk — how a month went,
        who's ahead or behind, what's driving the book, where to focus next.</p>`;
      if (busy) log.insertAdjacentHTML("beforeend", `<div class="mchat-msg assistant mchat-wait">Thinking…</div>`);
      log.scrollTop = log.scrollHeight;
    }

    function open() {
      panel.hidden = false;
      btn.hidden = true;
      draw();
      box.focus();
      // Build the figures now, so they're ready by the time the question is
      fetch("/api/mbr-chat", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ year, warm: true }) }).catch(() => {});
    }

    btn.addEventListener("click", open);
    panel.addEventListener("click", e => {
      const act = e.target.dataset && e.target.dataset.act;
      if (act === "close") { panel.hidden = true; btn.hidden = false; }
      if (act === "clear" && !busy) { history = []; save(); draw(); box.focus(); }
    });
    box.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const q = box.value.trim();
      if (!q || busy) return;
      history.push({ role: "user", content: q });
      box.value = "";
      busy = true; save(); draw();
      let reply;
      try {
        const resp = await fetch("/api/mbr-chat", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ year, messages: history }) });
        const d = await resp.json().catch(() => ({}));
        reply = d.reply || null;
        if (!reply) throw new Error(d.error || `The assistant couldn't answer (${resp.status}).`);
        history.push({ role: "assistant", content: reply });
      } catch (err) {
        // Drop the unanswered question so the conversation stays well-formed
        history.pop();
        box.value = q;
        busy = false; save(); draw();
        log.insertAdjacentHTML("beforeend", `<p class="mchat-err">${esc(err.message)}</p>`);
        return;
      }
      busy = false; save(); draw();
    });
  }

  // Called by mbr-contract.js once the page knows who's looking
  window.initMbrChat = function (y) {
    if (year !== null && y !== year) { history = []; save(); }
    year = y;
    build();
  };
})();
