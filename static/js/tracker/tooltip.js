import { computePosition, autoUpdate, offset, flip, shift } from "https://cdn.jsdelivr.net/npm/@floating-ui/dom@1.7.2/+esm";

const tooltip = document.getElementById("ui-tooltip");
const template = document.getElementById("bubble-tooltip-template").content;
let cleanup = null;

function showTooltip(referenceEl) {
  const clone = template.cloneNode(true);
  clone.querySelector('[data-field="title"]').textContent = referenceEl.dataset.title;
  clone.querySelector('[data-field="dot"]').classList.add(referenceEl.dataset.dot);

  tooltip.replaceChildren(clone);
  tooltip.classList.remove("opacity-0");
  tooltip.classList.add("opacity-100");

  if (cleanup) cleanup();
  cleanup = autoUpdate(referenceEl, tooltip, () => {
    computePosition(referenceEl, tooltip, {
      placement: "bottom-start",
      strategy: "fixed",
      middleware: [offset({ mainAxis: 16, crossAxis: 24 }), flip({ fallbackPlacements: ["top-start", "right-start", "left-start"], padding: 8 }), shift({ padding: 8 })]
    }).then(({ x, y }) => {
      Object.assign(tooltip.style, { left: `${x}px`, top: `${y}px` });
    });
  });
}

function hideTooltip() {
  tooltip.classList.replace("opacity-100", "opacity-0");
  if (cleanup) { cleanup(); cleanup = null; }
}

document.addEventListener("pointerenter", (e) => {
  if (!(e.target instanceof Element)) return;
  const bubble = e.target.closest(".bubble-box");
  if (bubble) showTooltip(bubble);
}, true);

document.addEventListener("pointerleave", (e) => {
  if (!(e.target instanceof Element)) return;
  const leftBubble = e.target.closest(".bubble-box");
  if (leftBubble && (!e.relatedTarget || !leftBubble.contains(e.relatedTarget))) {
    hideTooltip();
  }
}, true); 