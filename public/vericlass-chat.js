// VeriClass student chat: a paragraph, list, heading or table with any Hebrew
// letter lays out right to left; one without (English, code) left to right.
// (CSS alone can only follow the first letter, and many Hebrew sentences here
// start with an English term: "Trivy סורק image…".)
(() => {
  const HE = /[֐-׿]/;
  const SEL = [
    '[role="article"]', "li", "ul", "ol", "h1", "h2", "h3", "h4", "blockquote", "table",
  ].map((s) => ".message-content " + s).join(", ");

  const mark = (el) => {
    const dir = HE.test(el.textContent || "") ? "rtl" : "ltr";
    if (el.getAttribute("dir") !== dir) el.setAttribute("dir", dir);
  };
  const scan = () => document.querySelectorAll(SEL).forEach(mark);

  // Messages arrive and stream in token by token: look again after changes.
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    setTimeout(() => { queued = false; scan(); }, 30);
  }).observe(document.body, { childList: true, subtree: true, characterData: true });

  document.addEventListener("input", (e) => {
    const t = e.target;
    if (t && t.id === "chat-input") t.dir = HE.test(t.value) ? "rtl" : "ltr";
  });
  scan();
})();
