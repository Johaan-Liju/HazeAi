/*
 * The chat widget — Phase 2, Step 4 (Shadow DOM + saved conversation + polish).
 *
 * This one file draws the whole chat bubble: the round button in the corner,
 * the chat panel that opens, the streaming replies, and the "leave your number"
 * callback form. It's plain JavaScript (no React, no libraries) so it can be
 * dropped onto ANY website with a single <script> line:
 *
 *     <script src="https://yourserver.com/widget.js" data-company="coverfirst"></script>
 *
 * It reads two things from that <script> tag:
 *   data-company : which company this chat is for (must match companies.py)
 *   data-title   : the heading shown at the top of the panel (optional)
 * ...and it calls the /chat endpoint on whatever server this file came from.
 *
 * IMPORTANT — why Shadow DOM: customer sites have their own CSS, and many use a
 * global reset like  *{box-sizing:border-box;margin:0}  which would otherwise
 * leak in and wreck the widget's layout. We mount everything inside a shadow
 * root, which is a sealed bubble: the host page's styles can't reach in, and
 * ours can't leak out. That's what keeps the widget looking right everywhere.
 *
 * The conversation is saved in sessionStorage (per browser tab), so closing and
 * reopening the chat — or even reloading the page — picks up where the visitor
 * left off instead of greeting them from scratch every time. It's forgotten
 * when the tab closes, which is the polite amount of memory for a chat widget.
 */
(function () {
  // --- 1. Read config from our own <script> tag (must be done right away) ----
  var SCRIPT = document.currentScript;
  var COMPANY = (SCRIPT && SCRIPT.getAttribute("data-company")) || "coverfirst";
  var TITLE = (SCRIPT && SCRIPT.getAttribute("data-title")) || "Chat with us";
  // data-open="1" on the script tag (used on the demo pages) makes the chat
  // open by itself shortly after the page loads, instead of waiting for a
  // click. Customer sites just leave the attribute off.
  var AUTO_OPEN = !!(SCRIPT && SCRIPT.getAttribute("data-open"));
  // Talk to the endpoints on the SAME server that served this script.
  var API_BASE = SCRIPT ? new URL(SCRIPT.src).origin : "";

  var MAX_HISTORY = 10; // send only the last few turns (keeps token cost down)
  var GREETING = "Hi! How can I help you today?";

  // --- 2. The conversation, restored from this tab's saved copy --------------
  // sessionStorage survives page reloads but not closing the tab. `greeted`
  // remembers we've already said hello, so reopening the panel doesn't stack
  // up "Hi!" bubbles.
  var STORE_KEY = "cbw-chat-" + COMPANY;
  var saved = null;
  try {
    saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
  } catch (err) {}
  var messages = (saved && saved.messages) || [];
  var greeted = !!(saved && saved.greeted);
  var busy = false; // true while we're waiting for a reply

  function persist() {
    // Private-browsing modes can forbid storage — the chat still works then,
    // it just won't survive a reload. Never let a storage error break the UI.
    try {
      sessionStorage.setItem(
        STORE_KEY,
        JSON.stringify({ greeted: greeted, messages: messages })
      );
    } catch (err) {}
  }

  // --- 3. The widget's own styles (live inside the shadow root) --------------
  // :host is the widget's outer element. `all: initial` wipes out anything the
  // host page tried to pass down (fonts, colours), then we set our own. This is
  // the reset that makes us look the same on every site.
  var css = `
    :host { all: initial; position: fixed; bottom: 20px; right: 20px;
      z-index: 2147483000; }
    .cbw-root, .cbw-root *, .cbw-root *::before, .cbw-root *::after {
      box-sizing: border-box; margin: 0; padding: 0; }
    .cbw-root { font-family: ui-sans-serif, system-ui, -apple-system,
      "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 15px; line-height: 1.5; color: #1c1c28;
      -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }

    /* the round launcher button */
    .cbw-button { width: 60px; height: 60px; border-radius: 50%; border: none;
      cursor: pointer; background: linear-gradient(135deg, #6d5ff2, #4f46e5);
      color: #fff; display: flex; align-items: center; justify-content: center;
      box-shadow: 0 6px 20px rgba(79,70,229,.45), 0 2px 6px rgba(0,0,0,.12);
      transition: transform .18s ease, box-shadow .18s ease; }
    .cbw-button:hover { transform: translateY(-2px) scale(1.05);
      box-shadow: 0 10px 26px rgba(79,70,229,.5), 0 3px 8px rgba(0,0,0,.14); }
    .cbw-button svg { width: 28px; height: 28px; }

    /* the chat panel */
    .cbw-panel { display: none; flex-direction: column; width: 372px;
      max-width: calc(100vw - 40px); height: 560px;
      max-height: calc(100vh - 120px); background: #fff; border-radius: 20px;
      overflow: hidden; transform-origin: bottom right;
      box-shadow: 0 24px 60px rgba(23,23,60,.25), 0 4px 14px rgba(23,23,60,.12); }
    .cbw-panel.cbw-open { display: flex;
      animation: cbw-rise .22s cubic-bezier(.21,1.02,.55,1) both; }
    @keyframes cbw-rise {
      from { opacity: 0; transform: translateY(14px) scale(.97); }
      to   { opacity: 1; transform: none; } }

    /* header */
    .cbw-header { background: linear-gradient(135deg, #6d5ff2 0%, #4f46e5 60%,
      #4338ca 100%); color: #fff; padding: 15px 16px; display: flex;
      align-items: center; gap: 12px; }
    .cbw-avatar { width: 40px; height: 40px; border-radius: 50%; flex: none;
      background: rgba(255,255,255,.18); display: flex; align-items: center;
      justify-content: center; }
    .cbw-avatar svg { width: 22px; height: 22px; }
    .cbw-head-text { flex: 1; min-width: 0; }
    .cbw-title { font-weight: 600; font-size: 16px; letter-spacing: .1px;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .cbw-status { font-size: 12.5px; opacity: .9; display: flex;
      align-items: center; gap: 6px; margin-top: 2px; }
    .cbw-dot { width: 7px; height: 7px; border-radius: 50%; background: #4ade80;
      box-shadow: 0 0 0 3px rgba(74,222,128,.25); }
    .cbw-close { background: rgba(255,255,255,.14); border: none; color: #fff;
      width: 30px; height: 30px; border-radius: 50%; font-size: 18px;
      cursor: pointer; line-height: 1; flex: none; transition: background .15s; }
    .cbw-close:hover { background: rgba(255,255,255,.28); }

    /* the message area */
    .cbw-body { flex: 1; overflow-y: auto; padding: 16px 14px;
      background: #f4f5fb; display: flex; flex-direction: column; gap: 10px; }
    .cbw-msg { max-width: 82%; padding: 10px 14px; border-radius: 16px;
      font-size: 14.5px; line-height: 1.5; white-space: pre-wrap;
      word-wrap: break-word; animation: cbw-pop .18s ease both; }
    .cbw-instant { animation: none; } /* restored history shouldn't re-animate */
    @keyframes cbw-pop {
      from { opacity: 0; transform: translateY(6px); }
      to   { opacity: 1; transform: none; } }
    .cbw-user { align-self: flex-end; color: #fff;
      background: linear-gradient(135deg, #6d5ff2, #4f46e5);
      border-bottom-right-radius: 6px;
      box-shadow: 0 2px 6px rgba(79,70,229,.28); }
    .cbw-bot { align-self: flex-start; background: #fff; color: #1c1c28;
      border-bottom-left-radius: 6px;
      box-shadow: 0 1px 3px rgba(23,23,60,.08), 0 1px 2px rgba(23,23,60,.05); }

    /* the three bouncing "typing" dots */
    .cbw-typing { align-self: flex-start; background: #fff; border-radius: 16px;
      border-bottom-left-radius: 6px; padding: 13px 14px; display: flex;
      gap: 5px; box-shadow: 0 1px 3px rgba(23,23,60,.08); }
    .cbw-typing i { width: 7px; height: 7px; border-radius: 50%;
      background: #b9b9cc; animation: cbw-blink 1.2s infinite both; }
    .cbw-typing i:nth-child(2) { animation-delay: .18s; }
    .cbw-typing i:nth-child(3) { animation-delay: .36s; }
    @keyframes cbw-blink {
      0%, 70%, 100% { opacity: .35; transform: translateY(0); }
      35% { opacity: 1; transform: translateY(-3px); } }

    /* the type-a-message footer */
    .cbw-footer { display: flex; gap: 8px; padding: 12px; align-items: flex-end;
      border-top: 1px solid #ecedf5; background: #fff; }
    .cbw-input { flex: 1; resize: none; border: 1px solid #dcdde8;
      border-radius: 14px; padding: 10px 13px; font: inherit; font-size: 14.5px;
      line-height: 1.4; max-height: 90px; outline: none; background: #fafafd;
      transition: border-color .15s, box-shadow .15s; }
    .cbw-input:focus { border-color: #6d5ff2; background: #fff;
      box-shadow: 0 0 0 3px rgba(109,95,242,.15); }
    .cbw-send { border: none; width: 42px; height: 42px; border-radius: 50%;
      flex: none; background: linear-gradient(135deg, #6d5ff2, #4f46e5);
      color: #fff; cursor: pointer; display: flex; align-items: center;
      justify-content: center; transition: transform .15s, opacity .15s; }
    .cbw-send:hover { transform: scale(1.06); }
    .cbw-send:disabled { opacity: .45; cursor: default; transform: none; }
    .cbw-send svg { width: 18px; height: 18px; margin-left: 2px; }

    /* the "leave your number" callback form */
    .cbw-leadlink { border: none; background: #fff; color: #4f46e5;
      font-family: inherit; font-size: 13px; font-weight: 500; padding: 9px;
      cursor: pointer; text-align: center; border-top: 1px solid #ecedf5;
      width: 100%; }
    .cbw-leadlink:hover { background: #f7f7fd; }
    .cbw-lead { display: none; flex-direction: column; gap: 9px; padding: 14px;
      border-top: 1px solid #ecedf5; background: #fff; }
    .cbw-lead.cbw-open { display: flex; }
    .cbw-lead-title { font-size: 13.5px; font-weight: 600; color: #3f3f50; }
    .cbw-lead-phone, .cbw-lead-q { border: 1px solid #dcdde8;
      border-radius: 12px; padding: 10px 13px; font: inherit; font-size: 14.5px;
      outline: none; width: 100%; background: #fafafd;
      transition: border-color .15s, box-shadow .15s; }
    .cbw-lead-phone:focus, .cbw-lead-q:focus { border-color: #6d5ff2;
      background: #fff; box-shadow: 0 0 0 3px rgba(109,95,242,.15); }
    .cbw-lead-q { resize: none; min-height: 60px; }
    .cbw-lead-row { display: flex; gap: 8px; }
    .cbw-lead-send { flex: 1; border: none; color: #fff; border-radius: 12px;
      background: linear-gradient(135deg, #6d5ff2, #4f46e5); padding: 11px;
      font-family: inherit; font-weight: 600; font-size: 14px; cursor: pointer; }
    .cbw-lead-send:disabled { opacity: .5; cursor: default; }
    .cbw-lead-cancel { border: none; background: #eef0f6; color: #3f3f50;
      border-radius: 12px; padding: 11px 16px; cursor: pointer;
      font-family: inherit; font-size: 14px; }
    .cbw-lead-cancel:hover { background: #e4e6ef; }
  `;

  // Crisp inline icons (SVG scales cleanly, unlike emoji, and inherits color).
  var ICON_CHAT =
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
    '<path d="M12 3C6.5 3 2 6.9 2 11.7c0 2.6 1.3 4.9 3.4 6.5-.1 1-.6 2.3-1.6 3.3' +
    ' 1.8-.2 3.3-.9 4.4-1.7 1.2.4 2.4.6 3.8.6 5.5 0 10-3.9 10-8.7S17.5 3 12 3z"/></svg>';
  var ICON_SEND =
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
    '<path d="M3.4 20.4l17.8-8.4L3.4 3.6v6.4l12 2-12 2z"/></svg>';

  // --- 4. Build everything once the page body is ready -----------------------
  function init() {
    // The outer element that sits on the customer's page. Everything else lives
    // INSIDE its shadow root, sealed off from the page's CSS.
    var host = document.createElement("div");
    host.className = "cbw-host";
    // Belt-and-suspenders positioning in case a browser lacks Shadow DOM.
    host.style.cssText =
      "position:fixed;bottom:20px;right:20px;z-index:2147483000;";

    // Attach the shadow root (falls back to the plain element on ancient browsers).
    var mount = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

    var style = document.createElement("style");
    style.textContent = css;
    mount.appendChild(style);

    var root = document.createElement("div");
    root.className = "cbw-root";
    root.innerHTML =
      '<button class="cbw-button" title="Chat with us">' + ICON_CHAT + "</button>" +
      '<div class="cbw-panel">' +
      '  <div class="cbw-header">' +
      '    <div class="cbw-avatar">' + ICON_CHAT + "</div>" +
      '    <div class="cbw-head-text">' +
      '      <div class="cbw-title"></div>' +
      '      <div class="cbw-status"><span class="cbw-dot"></span>Online now</div>' +
      "    </div>" +
      '    <button class="cbw-close" title="Close">×</button>' +
      "  </div>" +
      '  <div class="cbw-body"></div>' +
      '  <div class="cbw-lead">' +
      '    <div class="cbw-lead-title">Leave your number — we\'ll call you back</div>' +
      '    <input class="cbw-lead-phone" type="tel" placeholder="Your phone number" />' +
      '    <textarea class="cbw-lead-q" rows="2" placeholder="How can we help you?"></textarea>' +
      '    <div class="cbw-lead-row">' +
      '      <button class="cbw-lead-cancel">Back</button>' +
      '      <button class="cbw-lead-send">Request callback</button>' +
      "    </div>" +
      "  </div>" +
      '  <div class="cbw-footer">' +
      '    <textarea class="cbw-input" rows="1" placeholder="Type a message…"></textarea>' +
      '    <button class="cbw-send" title="Send">' + ICON_SEND + "</button>" +
      "  </div>" +
      '  <button class="cbw-leadlink">📞 Leave your number for a callback</button>' +
      "</div>";
    mount.appendChild(root);
    document.body.appendChild(host);

    // Grab the pieces we need to control (from inside the shadow root).
    var button = root.querySelector(".cbw-button");
    var panel = root.querySelector(".cbw-panel");
    var closeBtn = root.querySelector(".cbw-close");
    var body = root.querySelector(".cbw-body");
    var input = root.querySelector(".cbw-input");
    var sendBtn = root.querySelector(".cbw-send");
    var footer = root.querySelector(".cbw-footer");
    var leadLink = root.querySelector(".cbw-leadlink");
    var lead = root.querySelector(".cbw-lead");
    var leadPhone = root.querySelector(".cbw-lead-phone");
    var leadQ = root.querySelector(".cbw-lead-q");
    var leadSend = root.querySelector(".cbw-lead-send");
    var leadCancel = root.querySelector(".cbw-lead-cancel");
    root.querySelector(".cbw-title").textContent = TITLE;

    // --- helpers ---
    function addBubble(role, text, instant) {
      var el = document.createElement("div");
      el.className =
        "cbw-msg " +
        (role === "user" ? "cbw-user" : "cbw-bot") +
        (instant ? " cbw-instant" : "");
      el.textContent = text;
      body.appendChild(el);
      body.scrollTop = body.scrollHeight; // keep newest message in view
      return el;
    }

    function showTyping() {
      var el = document.createElement("div");
      el.className = "cbw-typing";
      el.innerHTML = "<i></i><i></i><i></i>";
      body.appendChild(el);
      body.scrollTop = body.scrollHeight;
      return el;
    }

    // Rebuild the saved conversation (after a page reload). The greeting is
    // display-only — it lives in `greeted`, not in `messages` — so it comes
    // back first, then the real turns.
    if (greeted) addBubble("bot", GREETING, true);
    messages.forEach(function (m) {
      addBubble(m.role === "user" ? "user" : "bot", m.content, true);
    });

    function openPanel(autoOpened) {
      panel.classList.add("cbw-open");
      button.style.display = "none";
      if (!greeted) {
        // Say hello exactly once per visit — remembered across open/close
        // and reloads, so no more stacking "Hi!" bubbles.
        greeted = true;
        addBubble("bot", GREETING);
        persist();
      }
      body.scrollTop = body.scrollHeight;
      // When we open OURSELVES (demo pages), don't grab the keyboard — on a
      // phone that would shove the page up before the visitor has even read it.
      if (autoOpened !== true) input.focus();
    }

    function closePanel() {
      panel.classList.remove("cbw-open");
      button.style.display = "";
    }

    async function send() {
      var text = input.value.trim();
      if (!text || busy) return;
      input.value = "";
      addBubble("user", text);
      messages.push({ role: "user", content: text });
      persist();

      busy = true;
      sendBtn.disabled = true;
      var typing = showTyping();
      try {
        var res = await fetch(API_BASE + "/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            company: COMPANY,
            messages: messages.slice(-MAX_HISTORY),
          }),
        });
        if (!res.ok || !res.body) throw new Error("HTTP " + res.status);

        // Swap "typing…" for an empty bubble, then fill it as text streams in.
        typing.remove();
        var bubble = addBubble("bot", "");
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var full = "";
        while (true) {
          var chunk = await reader.read();
          if (chunk.done) break;
          full += decoder.decode(chunk.value, { stream: true });
          bubble.textContent = full; // repaint the bubble with everything so far
          body.scrollTop = body.scrollHeight;
        }
        if (full.trim() === "") {
          bubble.textContent = "Sorry — something went wrong. Please try again.";
        } else {
          messages.push({ role: "assistant", content: full });
          persist();
        }
      } catch (err) {
        typing.remove();
        addBubble("bot", "Sorry — I couldn't reach the server. Please try again.");
      } finally {
        busy = false;
        sendBtn.disabled = false;
        input.focus();
      }
    }

    // --- the callback form (lead capture) ---
    // Swaps the normal type-a-message footer for a "leave your number" form.
    function openLead() {
      lead.classList.add("cbw-open");
      footer.style.display = "none";
      leadLink.style.display = "none";
      // If they'd already typed a question, carry it over so they don't retype.
      if (input.value.trim()) leadQ.value = input.value.trim();
      leadPhone.focus();
    }

    function closeLead() {
      lead.classList.remove("cbw-open");
      footer.style.display = "";
      leadLink.style.display = "";
    }

    async function sendLead() {
      var phone = leadPhone.value.trim();
      if (!phone) {
        leadPhone.focus(); // a number is the one thing we really need
        return;
      }
      var question = leadQ.value.trim();
      leadSend.disabled = true;
      try {
        var res = await fetch(API_BASE + "/lead", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            company: COMPANY,
            phone: phone,
            question: question,
          }),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        leadPhone.value = "";
        leadQ.value = "";
        closeLead();
        addBubble("bot", "Thanks! We've got your number and will reach out soon. 📞");
      } catch (err) {
        closeLead();
        addBubble("bot", "Sorry — couldn't send that just now. Please try again.");
      } finally {
        leadSend.disabled = false;
      }
    }

    // --- wire up the buttons and keyboard ---
    button.addEventListener("click", function () { openPanel(); });
    closeBtn.addEventListener("click", closePanel);
    sendBtn.addEventListener("click", send);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault(); // Enter sends; Shift+Enter makes a new line
        send();
      }
    });
    leadLink.addEventListener("click", openLead);
    leadCancel.addEventListener("click", closeLead);
    leadSend.addEventListener("click", sendLead);

    // Demo pages ask us to open ourselves. Wait a beat so the visitor sees
    // the page land first — and skip it if they've already chatted this
    // visit (a reload shouldn't keep springing the panel back open).
    if (AUTO_OPEN && !greeted) {
      setTimeout(function () { openPanel(true); }, 900);
    }
  }

  // The script might load before <body> exists — wait for it if so.
  if (document.body) init();
  else document.addEventListener("DOMContentLoaded", init);
})();
