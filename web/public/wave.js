/* Nosey Bugger — "OI!" reveal.
 * Fades the message, then shows a moving wave: a Spline 3D scene if one is
 * configured (data-scene on #wave), otherwise a self-contained canvas fallback
 * so the effect is always gorgeous even with no scene set.
 */
(function () {
    "use strict";

    var oi = document.getElementById("oi");
    var wave = document.getElementById("wave");
    if (!wave) return;

    var scene = (wave.dataset.scene || "").trim();
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function reveal() {
        if (oi) oi.classList.add("gone");
        wave.classList.add("show");
        if (scene) {
            loadSpline(scene);
        } else {
            canvasWaves();
        }
    }

    // Give the reader a beat to see the message, then reveal.
    setTimeout(reveal, reduce ? 400 : 2200);

    // ── Spline path ────────────────────────────────────────────
    function loadSpline(url) {
        var viewer = document.createElement("spline-viewer");
        viewer.setAttribute("url", url);
        var s = document.createElement("script");
        s.type = "module";
        s.src = "https://unpkg.com/@splinetool/viewer@1.9.48/build/spline-viewer.js";
        s.onerror = canvasWaves; // network/CDN failure → fall back
        document.head.appendChild(s);
        wave.appendChild(viewer);
    }

    // ── Canvas fallback: layered sine waves ────────────────────
    function canvasWaves() {
        // If a spline-viewer is already present, don't double up.
        if (wave.querySelector("spline-viewer")) wave.innerHTML = "";

        var c = document.createElement("canvas");
        wave.appendChild(c);
        var ctx = c.getContext("2d");
        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        var w, h;

        function resize() {
            w = c.width = Math.floor(innerWidth * dpr);
            h = c.height = Math.floor(innerHeight * dpr);
            c.style.width = innerWidth + "px";
            c.style.height = innerHeight + "px";
        }
        resize();
        addEventListener("resize", resize);

        var layers = [
            { amp: 0.10, len: 0.9, speed: 0.6, y: 0.62, c: "rgba(124, 92, 255, 0.55)" },
            { amp: 0.08, len: 1.4, speed: -0.9, y: 0.70, c: "rgba(255, 92, 168, 0.45)" },
            { amp: 0.13, len: 0.6, speed: 0.4, y: 0.78, c: "rgba(14, 124, 134, 0.55)" },
            { amp: 0.06, len: 2.1, speed: 1.2, y: 0.85, c: "rgba(255, 255, 255, 0.18)" }
        ];

        function frame(t) {
            var time = t * 0.001;
            ctx.clearRect(0, 0, w, h);
            for (var i = 0; i < layers.length; i++) {
                var L = layers[i];
                ctx.beginPath();
                ctx.moveTo(0, h);
                for (var x = 0; x <= w; x += 8 * dpr) {
                    var k = (x / w) * Math.PI * 2 * (1 / L.len) * 2;
                    var yy = h * L.y + Math.sin(k + time * L.speed) * h * L.amp
                        + Math.sin(k * 0.5 + time * L.speed * 0.7) * h * L.amp * 0.5;
                    ctx.lineTo(x, yy);
                }
                ctx.lineTo(w, h);
                ctx.closePath();
                ctx.fillStyle = L.c;
                ctx.fill();
            }
            requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
    }
})();
