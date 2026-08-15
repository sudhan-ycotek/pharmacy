var modalStack = [];
var lastTriggerElement = null;

function getFocusableElements(modalEl) {
  return Array.prototype.slice.call(
    modalEl.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
      'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  ).filter(function (el) { return el.offsetParent !== null; });
}

function openModal(id) {
  var el = document.getElementById(id);
  if (!el) return;
  lastTriggerElement = document.activeElement;
  el.classList.add("open");
  modalStack.push(id);
  var sidebar = document.querySelector(".sidebar");
  if (sidebar) { sidebar.setAttribute("inert", ""); }
  var focusTarget = el.querySelector("[autofocus]") || getFocusableElements(el)[0];
  if (focusTarget) { focusTarget.focus(); }
}

function closeModal(id) {
  var el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("open");
  modalStack = modalStack.filter(function (m) { return m !== id; });
  if (modalStack.length === 0) {
    var sidebar = document.querySelector(".sidebar");
    if (sidebar) { sidebar.removeAttribute("inert"); }
  }
  if (lastTriggerElement && typeof lastTriggerElement.focus === "function") {
    lastTriggerElement.focus();
  }
}

document.addEventListener("keydown", function (e) {
  if (modalStack.length === 0) return;
  var topEl = document.getElementById(modalStack[modalStack.length - 1]);
  if (!topEl) return;
  if (e.key === "Escape") {
    e.preventDefault();
    closeModal(modalStack[modalStack.length - 1]);
    return;
  }
  if (e.key === "Tab") {
    var focusables = getFocusableElements(topEl);
    if (focusables.length === 0) return;
    var first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});

document.addEventListener("click", function (e) {
  if (e.target.classList.contains("modal-backdrop")) {
    closeModal(e.target.id);
  }
});
