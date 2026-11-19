(function () {
  "use strict";

  var root = document.documentElement;

  function storageGet(key, fallback) {
    try {
      return localStorage.getItem(key) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function storageSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (e) {}
  }

  function applyTheme(theme) {
    root.dataset.theme = theme;
    storageSet("ostium-theme", theme);
    window.dispatchEvent(new CustomEvent("ostium:theme", { detail: { theme: theme } }));
  }

  function initTheme() {
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    button.addEventListener("click", function () {
      applyTheme(root.dataset.theme === "light" ? "dark" : "light");
    });
  }

  function toast(message, tone) {
    var stack = document.querySelector(".toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "toast-stack";
      stack.setAttribute("aria-live", "polite");
      document.body.appendChild(stack);
    }
    var node = document.createElement("div");
    node.className = "toast toast--" + (tone || "info");
    node.textContent = message;
    stack.appendChild(node);
    setTimeout(function () {
      node.style.opacity = "0";
      setTimeout(function () {
        node.remove();
      }, 220);
    }, 2200);
  }

  function initCopy() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-copy]");
      if (!button) return;
      event.preventDefault();
      var value = button.getAttribute("data-copy");
      if (!value) {
        var scope = button.closest(".copy-field");
        var code = scope ? scope.querySelector("code") : null;
        value = code ? code.textContent.trim() : "";
      }
      if (!value) return;
      var done = function () {
        toast("已复制到剪贴板", "success");
        var original = button.getAttribute("aria-label");
        button.setAttribute("aria-label", "已复制");
        setTimeout(function () {
          if (original) button.setAttribute("aria-label", original);
        }, 1400);
      };
      var fallbackCopy = function () {
        var area = document.createElement("textarea");
        area.value = value;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        var copied = false;
        try {
          copied = document.execCommand("copy");
        } catch (e) {
          copied = false;
        }
        area.remove();
        if (copied) done();
      };
      if (navigator.clipboard && window.isSecureContext) {
        // Clipboard permissions can be denied even on HTTPS. Fall back to the
        // legacy path instead of failing silently.
        navigator.clipboard.writeText(value).then(done, fallbackCopy);
      } else {
        fallbackCopy();
      }
    });
  }

  function initConfirm() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-confirm]");
      if (!button || !button.form) return;
      var message = button.getAttribute("data-confirm") || "确认执行此操作？";
      if (!window.confirm(message)) event.preventDefault();
    });
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!form.matches("form[data-confirm]")) return;
      if (form.dataset.confirmed === "1") return;
      var message = form.getAttribute("data-confirm") || "确认执行此操作？";
      if (!window.confirm(message)) {
        event.preventDefault();
      } else {
        form.dataset.confirmed = "1";
      }
    });
  }

  function initCommandPalette() {
    var modal = document.getElementById("command-palette");
    if (!modal) return;
    var input = document.getElementById("command-input");
    var list = document.getElementById("command-list");
    var shell = document.querySelector(".app-shell");
    var open = function () {
      modal.classList.remove("hidden");
      if (shell) shell.inert = true;
      if (input) {
        input.value = "";
        setTimeout(function () {
          input.focus();
        }, 20);
      }
      if (list) {
        Array.prototype.forEach.call(list.children, function (item) {
          item.classList.remove("is-highlighted");
        });
      }
    };
    var close = function () {
      modal.classList.add("hidden");
      if (shell) shell.inert = false;
    };
    var openButton = document.getElementById("command-open");
    var closeButton = document.getElementById("command-close");
    if (openButton) openButton.addEventListener("click", open);
    if (closeButton) closeButton.addEventListener("click", close);
    modal.addEventListener("click", function (event) {
      if (event.target === modal) close();
    });
    modal.addEventListener("keydown", function (event) {
      if (event.key !== "Tab") return;
      var focusable = Array.prototype.filter.call(
        modal.querySelectorAll("a[href], button, input, [tabindex]:not([tabindex='-1'])"),
        function (node) { return node.offsetParent !== null; }
      );
      if (!focusable.length) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    document.addEventListener("keydown", function (event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        modal.classList.contains("hidden") ? open() : close();
      }
      if (event.key === "Escape" && !modal.classList.contains("hidden")) close();
    });
    if (input && list) {
      input.addEventListener("input", function () {
        var query = input.value.toLowerCase();
        Array.prototype.forEach.call(list.children, function (item) {
          item.style.display = item.textContent.toLowerCase().indexOf(query) >= 0 ? "" : "none";
        });
      });
      input.addEventListener("keydown", function (event) {
        if (event.key !== "Enter") return;
        var visible = Array.prototype.filter.call(list.children, function (item) {
          return item.style.display !== "none";
        });
        if (visible.length) {
          event.preventDefault();
          visible[0].click();
        }
      });
    }
  }

  function initCharts() {
    var dataNode = document.getElementById("traffic-data");
    var canvas = document.getElementById("traffic-chart");
    if (!dataNode || !canvas || typeof window.Chart === "undefined") return;
    var rows;
    try {
      rows = JSON.parse(dataNode.textContent);
    } catch (e) {
      return;
    }
    var theme = root.dataset.theme;
    var colors = theme === "light"
      ? { text: "#64748b", grid: "rgba(15,23,42,.08)", up: "#0f766e", down: "#2563eb" }
      : { text: "#6f819b", grid: "rgba(148,163,184,.10)", up: "#5eead4", down: "#60a5fa" };
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function build() {
      var context = canvas.getContext("2d");
      var upGradient = context.createLinearGradient(0, 0, 0, canvas.parentElement.clientHeight || 260);
      upGradient.addColorStop(0, theme === "light" ? "rgba(15,118,110,.24)" : "rgba(94,234,212,.30)");
      upGradient.addColorStop(1, "rgba(94,234,212,0)");
      var downGradient = context.createLinearGradient(0, 0, 0, canvas.parentElement.clientHeight || 260);
      downGradient.addColorStop(0, theme === "light" ? "rgba(37,99,235,.18)" : "rgba(96,165,250,.22)");
      downGradient.addColorStop(1, "rgba(96,165,250,0)");

      if (window.__ostiumChart) {
        window.__ostiumChart.destroy();
      }
      window.__ostiumChart = new window.Chart(canvas, {
        type: "line",
        data: {
          labels: rows.map(function (row) { return row.label; }),
          datasets: [
            {
              label: "上行",
              data: rows.map(function (row) { return row.uplink; }),
              borderColor: colors.up,
              backgroundColor: upGradient,
              fill: true,
              tension: 0.38,
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 3,
              pointHoverBackgroundColor: colors.up
            },
            {
              label: "下行",
              data: rows.map(function (row) { return row.downlink; }),
              borderColor: colors.down,
              backgroundColor: downGradient,
              fill: true,
              tension: 0.38,
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 3,
              pointHoverBackgroundColor: colors.down
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: reduced ? false : { duration: 450 },
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: theme === "light" ? "#ffffff" : "#0d1423",
              borderColor: theme === "light" ? "rgba(15,23,42,.12)" : "rgba(148,163,184,.2)",
              borderWidth: 1,
              titleColor: theme === "light" ? "#0f172a" : "#eef4ff",
              bodyColor: theme === "light" ? "#475569" : "#a8b6cc",
              padding: 10,
              cornerRadius: 9,
              callbacks: {
                label: function (item) {
                  var value = item.parsed.y || 0;
                  var units = ["B", "KiB", "MiB", "GiB", "TiB"];
                  var index = 0;
                  while (value >= 1024 && index < units.length - 1) {
                    value /= 1024;
                    index += 1;
                  }
                  return item.dataset.label + " " + (index ? value.toFixed(1) : Math.round(value)) + " " + units[index];
                }
              }
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: colors.text, font: { size: 10 }, maxRotation: 0 },
              border: { display: false }
            },
            y: {
              beginAtZero: true,
              grid: { color: colors.grid },
              border: { display: false },
              ticks: {
                color: colors.text,
                font: { size: 10 },
                callback: function (value) {
                  var units = ["B", "K", "M", "G", "T"];
                  var index = 0;
                  while (value >= 1024 && index < units.length - 1) {
                    value /= 1024;
                    index += 1;
                  }
                  return (index ? value.toFixed(value >= 10 ? 0 : 1) : Math.round(value)) + units[index];
                }
              }
            }
          }
        }
      });
    }

    build();
    window.addEventListener("ostium:theme", function () {
      theme = root.dataset.theme;
      colors = theme === "light"
        ? { text: "#64748b", grid: "rgba(15,23,42,.08)", up: "#0f766e", down: "#2563eb" }
        : { text: "#6f819b", grid: "rgba(148,163,184,.10)", up: "#5eead4", down: "#60a5fa" };
      build();
    });
  }

  function initHtmx() {
    if (!window.htmx) return;
    document.body.addEventListener("htmx:configRequest", function (event) {
      var token = document.querySelector("input[name=csrfmiddlewaretoken]");
      if (token) event.detail.headers["X-CSRFToken"] = token.value;
    });
  }

  function initPasswordToggles() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-toggle-password]");
      if (!button) return;
      var target = document.querySelector(button.getAttribute("data-toggle-password"));
      if (!target) return;
      target.type = target.type === "password" ? "text" : "password";
    });
  }

  function init() {
    initTheme();
    initCopy();
    initConfirm();
    initCommandPalette();
    initCharts();
    initHtmx();
    initPasswordToggles();
  }

  if (document.readyState === "complete") {
    init();
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})();
