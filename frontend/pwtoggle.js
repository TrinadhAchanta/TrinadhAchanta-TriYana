/* Show / hide password: adds an eye button to every password box, including ones drawn later. */
(function () {
  const EYE = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  const EYE_OFF = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 5.1A10.4 10.4 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7c1.8 0 3.4-.5 4.8-1.3"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';
  const css = document.createElement("style");
  css.textContent = `.pw-wrap{position:relative;display:block;width:100%}.pw-wrap input{width:100%;padding-right:44px;box-sizing:border-box}
.pw-eye{position:absolute;right:4px;top:50%;transform:translateY(-50%);width:36px;height:36px;display:grid;place-items:center;
border:0;background:none;color:var(--muted,#6b7a74);cursor:pointer;border-radius:8px;padding:0}.pw-eye:hover{color:var(--text,inherit)}
.pw-eye:focus-visible{outline:2px solid currentColor;outline-offset:1px}`;
  document.head.appendChild(css);

  function enhance(input) {
    if (input.dataset.pwEye) return;
    input.dataset.pwEye = "1";
    const wrap = document.createElement("span");
    wrap.className = "pw-wrap";
    if (input.style.flex) { wrap.style.flex = input.style.flex; wrap.style.minWidth = input.style.minWidth; wrap.style.width = "auto"; }
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "pw-eye"; btn.innerHTML = EYE;
    btn.setAttribute("aria-label", "Show password"); btn.setAttribute("aria-pressed", "false");
    btn.onclick = (e) => {
      e.preventDefault();
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.innerHTML = show ? EYE_OFF : EYE;
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
      btn.setAttribute("aria-pressed", String(show));
      input.focus();
    };
    wrap.appendChild(btn);
  }
  const scan = (root) => root.querySelectorAll && root.querySelectorAll('input[type="password"]:not([data-pw-eye])').forEach(enhance);
  const start = () => {
    scan(document);
    new MutationObserver((muts) => muts.forEach((m) => m.addedNodes.forEach((n) => n.nodeType === 1 && (n.matches?.('input[type="password"]') ? enhance(n) : scan(n)))))
      .observe(document.body, { childList: true, subtree: true });
  };
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);
})();
