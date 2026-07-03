/*
 * The chat widget — Phase 2, Step 4.
 *
 * This one file draws the whole chat bubble: the round button in the corner,
 * the chat panel that opens, and the typing/sending logic. It's plain
 * JavaScript (no React, no libraries) so it can be dropped onto ANY website
 * with a single <script> line — that's the end goal (Step 8):
 *
 *     <script src="https://yourserver.com/widget.js" data-company="coverfirst"></script>
 *
 * It reads two things from that <script> tag:
 *   data-company : which company this chat is for (must match companies.py)
 *   data-title   : the heading shown at the top of the panel (optional)
 * ...and it calls the /chat endpoint on whatever server this file came from.
 */
(function () {
  // --- 1. Read config from our own <script> tag (must be done right away) ----
  var SCRIPT = document.currentScript;
  var COMPANY = (SCRIPT && SCRIPT.getAttribute("data-company")) || "coverfirst";
  var TITLE = (SCRIPT && SCRIPT.getAttribute("data-title")) || "Chat with us";
  // Talk to the /chat endpoint on the SAME server that served this script.
  var API_BASE = SCRIPT ? new URL(SCRIPT.src).origin : "";

  var MAX_HISTORY = 10; // send only the last few turns (keeps token cost down)

  // The conversation so far, kept in the browser's memory (not on the server).
  var messages = [];
  var busy = false; // true while we're waiting for a reply

  // --- 2. The widget's own styles (prefixed "cbw-" so they can't clash) ------
  var css = `
    .cbw-root { position: fixed; bottom: 20px; right: 20px; z-index: 999999;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
    .cbw-button { width: 60px; height: 60px; border-radius: 50%; border: none;
      background: #4f46e5; color: #fff; font-size: 28px; cursor: pointer;
      box-shadow: 0 4px 14px rgba(0,0,0,.25); transition: transform .15s; }
    .cbw-button:hover { transform: scale(1.06); }
    .cbw-panel { display: none; flex-direction: column; width: 360px;
      max-width: calc(100vw - 40px); height: 520px;
      max-height: calc(100vh - 120px); background: #fff; border-radius: 16px;
      overflow: hidden; box-shadow: 0 12px 32px rgba(0,0,0,.28); }
    .cbw-panel.cbw-open { display: flex; }
    .cbw-header { background: #4f46e5; color: #fff; padding: 14px 16px;
      font-weight: 600; display: flex; justify-content: space-between;
      align-items: center; }
    .cbw-close { background: none; border: none; color: #fff; font-size: 22px;
      cursor: pointer; line-height: 1; }
    .cbw-body { flex: 1; overflow-y: auto; padding: 14px; background: #f7f7f9;
      display: flex; flex-direction: column; gap: 10px; }
    .cbw-msg { max-width: 80%; padding: 9px 13px; border-radius: 14px;
      font-size: 14px; line-height: 1.45; white-space: pre-wrap;
      word-wrap: break-word; }
    .cbw-user { align-self: flex-end; background: #4f46e5; color: #fff;
      border-bottom-right-radius: 4px; }
    .cbw-bot { align-self: flex-start; background: #fff; color: #1a1a1a;
      border: 1px solid #e5e5ea; border-bottom-left-radius: 4px; }
    .cbw-typing { align-self: flex-start; color: #888; font-size: 13px;
      padding: 4px 6px; }
    .cbw-footer { display: flex; gap: 8px; padding: 10px; border-top:
      1px solid #ececf0; background: #fff; }
    .cbw-input { flex: 1; resize: none; border: 1px solid #d5d5dd;
      border-radius: 10px; padding: 9px 11px; font: inherit; font-size: 14px;
      max-height: 90px; outline: none; }
    .cbw-input:focus { border-color: #4f46e5; }
    .cbw-send { border: none; background: #4f46e5; color: #fff; border-radius:
      10px; padding: 0 16px; font-weight: 600; cursor: pointer; }
    .cbw-send:disabled { opacity: .5; cursor: default; }
  `;

  // --- 3. Build everything once the page body is ready -----------------------
  function init() {
    var style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    var root = document.createElement("div");
    root.className = "cbw-root";
    root.innerHTML =
      '<button class="cbw-button" title="Chat with us">💬</button>' +
      '<div class="cbw-panel">' +
      '  <div class="cbw-header"><span></span>' +
      '    <button class="cbw-close" title="Close">×</button></div>' +
      '  <div class="cbw-body"></div>' +
      '  <div class="cbw-footer">' +
      '    <textarea class="cbw-input" rows="1" placeholder="Type a message…"></textarea>' +
      '    <button class="cbw-send">Send</button>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(root);

    // Grab the pieces we need to control.
    var button = root.querySelector(".cbw-button");
    var panel = root.querySelector(".cbw-panel");
    var closeBtn = root.querySelector(".cbw-close");
    var body = root.querySelector(".cbw-body");
    var input = root.querySelector(".cbw-input");
    var sendBtn = root.querySelector(".cbw-send");
    root.querySelector(".cbw-header span").textContent = TITLE;

    // --- helpers ---
    function addBubble(role, text) {
      var el = document.createElement("div");
      el.className = "cbw-msg " + (role === "user" ? "cbw-user" : "cbw-bot");
      el.textContent = text;
      body.appendChild(el);
      body.scrollTop = body.scrollHeight; // keep newest message in view
      return el;
    }

    function showTyping() {
      var el = document.createElement("div");
      el.className = "cbw-typing";
      el.textContent = "typing…";
      body.appendChild(el);
      body.scrollTop = body.scrollHeight;
      return el;
    }

    function openPanel() {
      panel.classList.add("cbw-open");
      button.style.display = "none";
      if (messages.length === 0) {
        // A friendly greeting — shown in the panel, not sent to the API.
        addBubble("bot", "Hi! How can I help you today?");
      }
      input.focus();
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

    // --- wire up the buttons and keyboard ---
    button.addEventListener("click", openPanel);
    closeBtn.addEventListener("click", closePanel);
    sendBtn.addEventListener("click", send);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault(); // Enter sends; Shift+Enter makes a new line
        send();
      }
    });
  }

  // The script might load before <body> exists — wait for it if so.
  if (document.body) init();
  else document.addEventListener("DOMContentLoaded", init);
})();
