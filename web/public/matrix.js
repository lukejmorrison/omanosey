/* Omarchy-flavoured matrix / rain / thunder behind the floating QR. */
(function () {
  var body = document.body;
  if (!body.classList.contains("screen-owner")) return;

  var canvas = document.getElementById("matrix");
  var thunder = document.getElementById("thunder");
  var plate = document.getElementById("qr-plate");
  if (!canvas || !plate) return;

  var ctx = canvas.getContext("2d");
  if (!ctx) return;

  var monitor = body.getAttribute("data-monitor") || "";
  var cols = [];
  var glyphW = 14;
  var glyphH = 18;
  var reduced = false;
  try {
    reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (error) {}

  var CHARSET =
    "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789<>{}[]#@$%&*";
  var modes = ["matrix", "rain", "thunder"];
  var mode = "matrix";
  var modeUntil = 0;
  var flash = 0;
  var showing = false;
  var lastSlot = -1;
  var fadeTimer = null;

  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = window.innerWidth;
    var h = window.innerHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    glyphW = Math.max(12, Math.floor(w / 90));
    glyphH = Math.floor(glyphW * 1.25);
    var n = Math.ceil(w / glyphW) + 1;
    cols = [];
    for (var i = 0; i < n; i++) {
      cols.push({
        y: Math.random() * h,
        speed: 0.35 + Math.random() * 1.4,
        len: 8 + Math.floor(Math.random() * 18),
        bright: Math.random(),
      });
    }
  }

  function pickMode(now) {
    if (now < modeUntil) return;
    mode = modes[Math.floor(Math.random() * modes.length)];
    modeUntil = now + 8000 + Math.random() * 10000;
    if (mode === "thunder" && Math.random() < 0.55) flash = 1;
  }

  function drawFrame(now) {
    var w = window.innerWidth;
    var h = window.innerHeight;
    pickMode(now);

    // Trail: deep Omarchy purple-black.
    ctx.fillStyle = mode === "thunder" ? "rgba(6, 4, 14, 0.28)" : "rgba(4, 6, 12, 0.22)";
    ctx.fillRect(0, 0, w, h);

    if (flash > 0.02) {
      ctx.fillStyle = "rgba(220, 230, 255, " + (flash * 0.55) + ")";
      ctx.fillRect(0, 0, w, h);
      if (thunder) thunder.style.opacity = String(flash * 0.85);
      flash *= 0.86;
    } else if (thunder) {
      thunder.style.opacity = "0";
      if (mode === "thunder" && Math.random() < 0.008) flash = 0.7 + Math.random() * 0.5;
    }

    ctx.font = "bold " + glyphH + "px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
    ctx.textBaseline = "top";

    for (var i = 0; i < cols.length; i++) {
      var col = cols[i];
      var x = i * glyphW;
      var headY = col.y;
      var green = mode === "rain" ? 170 : 230;
      var cyan = mode === "matrix" ? 40 : 120;

      for (var j = 0; j < col.len; j++) {
        var gy = headY - j * glyphH;
        if (gy < -glyphH || gy > h) continue;
        var ch = CHARSET.charAt((i * 17 + j * 3 + Math.floor(now / 90)) % CHARSET.length);
        var alpha = Math.max(0.08, 1 - j / col.len);
        if (j === 0) {
          ctx.fillStyle = "rgba(230, 255, 240, " + alpha + ")";
        } else if (mode === "thunder" && j < 3) {
          ctx.fillStyle = "rgba(190, 200, 255, " + alpha + ")";
        } else {
          ctx.fillStyle =
            "rgba(" +
            Math.floor(20 + cyan * col.bright) +
            "," +
            Math.floor(green * alpha) +
            "," +
            Math.floor(80 + cyan) +
            "," +
            alpha +
            ")";
        }
        ctx.fillText(ch, x, gy);
      }

      col.y += col.speed * glyphH * (mode === "rain" ? 0.55 : 0.85);
      if (col.y - col.len * glyphH > h) {
        col.y = -Math.random() * h * 0.3;
        col.speed = 0.35 + Math.random() * 1.4;
        col.len = 8 + Math.floor(Math.random() * 18);
        col.bright = Math.random();
      }
    }

    if (!reduced) requestAnimationFrame(drawFrame);
  }

  function placePlate() {
    var size = Math.min(window.innerWidth, window.innerHeight) * 0.28;
    size = Math.max(140, Math.min(size, 280));
    plate.style.width = size + "px";
    var pad = 48;
    var maxX = Math.max(pad, window.innerWidth - size - pad);
    var maxY = Math.max(pad, window.innerHeight - size - pad);
    var x = pad + Math.random() * (maxX - pad);
    var y = pad + Math.random() * (maxY - pad);
    plate.style.left = Math.round(x) + "px";
    plate.style.top = Math.round(y) + "px";
  }

  function setVisible(on, relocate) {
    if (fadeTimer) {
      clearTimeout(fadeTimer);
      fadeTimer = null;
    }
    if (on) {
      if (relocate || !showing) placePlate();
      plate.classList.add("visible");
      showing = true;
    } else {
      plate.classList.remove("visible");
      showing = false;
    }
  }

  function applyLead(data) {
    if (!data) return;
    var should = !!data.show;
    // Solo monitor still moves each slot.
    if (!data.monitors || data.monitors.length <= 1) should = true;
    var slot = typeof data.slot === "number" ? data.slot : -1;
    if (should) {
      var moved = slot !== lastSlot;
      lastSlot = slot;
      setVisible(true, moved);
    } else {
      lastSlot = slot;
      setVisible(false, false);
    }
  }

  function pollLead() {
    var q = "/screen-lead?monitor=" + encodeURIComponent(monitor || "solo");
    fetch(q, { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(applyLead)
      .catch(function () {
        // Offline: still show QR so the kiosk stays useful.
        setVisible(true, !showing);
      });
  }

  window.addEventListener("resize", function () {
    resize();
    if (showing) placePlate();
  });

  resize();
  ctx.fillStyle = "#05060c";
  ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
  if (!reduced) requestAnimationFrame(drawFrame);
  else {
    // Static sprinkle for reduced motion.
    ctx.fillStyle = "rgba(40, 180, 90, 0.35)";
    for (var i = 0; i < 80; i++) {
      ctx.fillText(
        CHARSET.charAt(i % CHARSET.length),
        Math.random() * window.innerWidth,
        Math.random() * window.innerHeight
      );
    }
  }

  pollLead();
  setInterval(pollLead, 2000);
})();
