/**
 * "Feedback to Jason" — on every 1:1 and MBR page (Jason, Oct 2026).
 *
 * A page opts in with <body data-feedback-page="MBR">. The button goes into
 * the element marked data-feedback-host (or is the existing #feedback-open).
 * The sender comes from their login, not a typed field, so feedback can't be
 * misattributed; a page can say what's on screen by setting
 * window.feedbackContext = () => "Louis Warren, September 2026".
 */
(function () {
  var ICON = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>';

  function page() {
    return document.body.getAttribute("data-feedback-page") || document.title;
  }

  function show() {
    var overlay = document.getElementById("fb-modal");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "fb-modal";
      overlay.className = "modal-overlay";
      overlay.innerHTML =
        '<div class="modal-box">' +
        '  <div class="modal-header">' +
        '    <span class="modal-title">Feedback to Jason</span>' +
        '    <button class="modal-close" id="fb-close" aria-label="Close">✕</button>' +
        '  </div>' +
        '  <div class="modal-body">' +
        '    <p class="mbr-note" style="margin-top:0">Anything that\'s wrong, missing, confusing or' +
        '      would make this more useful. It goes straight to Jason\'s inbox with your name on it.</p>' +
        '    <textarea id="fb-text" rows="6" class="oto-in" placeholder="What would you change?"></textarea>' +
        '    <div class="mbr-savebar" style="margin-top:12px">' +
        '      <button class="save-btn" id="fb-send">Send</button>' +
        '      <span class="mbr-saved-note" id="fb-note"></span>' +
        '    </div>' +
        '  </div>' +
        '</div>';
      document.body.appendChild(overlay);
      overlay.addEventListener("click", function (e) { if (e.target === overlay) overlay.style.display = "none"; });
      overlay.querySelector("#fb-close").addEventListener("click", function () { overlay.style.display = "none"; });
      overlay.querySelector("#fb-send").addEventListener("click", send);
    }
    overlay.querySelector("#fb-note").textContent = "";
    overlay.style.display = "flex";
    setTimeout(function () { overlay.querySelector("#fb-text").focus(); }, 50);
  }

  async function send() {
    var btn = document.getElementById("fb-send");
    var box = document.getElementById("fb-text");
    var note = document.getElementById("fb-note");
    if (!box.value.trim()) { note.textContent = "Write something first."; return; }
    btn.disabled = true; btn.textContent = "Sending…";
    try {
      var context = "";
      try { context = (window.feedbackContext && window.feedbackContext()) || ""; } catch (e) {}
      var resp = await fetch("/api/feedback", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: box.value, page: page(), context: context }),
      });
      var d = await resp.json();
      if (!d.ok) throw new Error(d.error || "unknown error");
      note.textContent = "Sent — thank you.";
      box.value = "";
      setTimeout(function () { document.getElementById("fb-modal").style.display = "none"; }, 1200);
    } catch (e) {
      note.textContent = "Could not send: " + e.message;
    }
    btn.disabled = false; btn.textContent = "Send";
  }

  function init() {
    var btn = document.getElementById("feedback-open");
    if (!btn) {
      var host = document.querySelector("[data-feedback-host]");
      if (!host) return;
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "feedback-btn";
      btn.id = "feedback-open";
      btn.innerHTML = ICON + "<span>Feedback to Jason</span>";
      host.appendChild(btn);
    }
    btn.addEventListener("click", show);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
