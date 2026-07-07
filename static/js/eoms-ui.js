(function () {
  function ready(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback);
      return;
    }
    callback();
  }

  ready(function () {
    var shell = document.querySelector("[data-eoms-shell]");
    if (!shell) {
      return;
    }

    var collapseButton = document.querySelector("[data-eoms-collapse-sidebar]");
    var mobileButton = document.querySelector("[data-eoms-mobile-sidebar]");

    if (collapseButton) {
      collapseButton.addEventListener("click", function () {
        shell.classList.toggle("sidebar-collapsed");
      });
    }

    if (mobileButton) {
      mobileButton.addEventListener("click", function () {
        shell.classList.toggle("sidebar-open");
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        shell.classList.remove("sidebar-open");
      }
    });

    document.querySelectorAll(".eoms-nav a").forEach(function (link) {
      link.addEventListener("click", function () {
        shell.classList.remove("sidebar-open");
      });
    });
  });
})();
