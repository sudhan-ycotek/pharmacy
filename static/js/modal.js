function openModal(id) {
  var el = document.getElementById(id);
  if (el) { el.classList.add("open"); }
}

function closeModal(id) {
  var el = document.getElementById(id);
  if (el) { el.classList.remove("open"); }
}

document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") {
    document.querySelectorAll(".modal-backdrop.open").forEach(function (m) {
      m.classList.remove("open");
    });
  }
});

document.addEventListener("click", function (e) {
  if (e.target.classList.contains("modal-backdrop")) {
    e.target.classList.remove("open");
  }
});
