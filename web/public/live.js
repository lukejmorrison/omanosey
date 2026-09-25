(function () {
  var body = document.body;
  var role = body.getAttribute("data-live") || "";
  if (!role) return;

  var nonce = body.getAttribute("data-nonce") || "";
  var alertPanel = document.getElementById("alert-panel");
  var alertNote = document.getElementById("alert-note");
  var alertSnap = document.getElementById("alert-snap");
  var alarmDismiss = document.getElementById("alarm-dismiss");
  // Legacy full-screen alarm id (ignore if absent)
  var alarm = document.getElementById("alarm");
  var statusEl = document.getElementById("live-status");
  var armBtn = document.getElementById("arm");
  var talk = document.getElementById("talk");
  var proto = location.protocol === "https:" ? "wss:" : "ws:";
  var socket = null;
  var audioCtx = null;
  var armed = role !== "desk";
  var alarmTimer = null;
  var seenComments = {};
  var unlockAudio = null;
  var lastScanNonce = "";
  var lastReplyKey = "";
  var wsOpen = false;
  var DING_WAV = "";
  var ALARM_WAV = "";

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function draw(url) {
    var box = document.getElementById("qr");
    if (!box || typeof qrcode !== "function") return;
    var qr = qrcode(0, "M");
    qr.addData(url);
    qr.make();
    box.innerHTML = qr.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
  }

  function buildToneWav(notes) {
    // notes: [{freq, ms, gain}]
    var rate = 22050;
    var totalMs = 0;
    notes.forEach(function (n) { totalMs += n.ms; });
    var n = Math.floor(rate * (totalMs / 1000));
    var dataSize = n * 2;
    var buf = new ArrayBuffer(44 + dataSize);
    var view = new DataView(buf);
    function str(offset, s) {
      for (var i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
    }
    str(0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    str(8, "WAVE");
    str(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    str(36, "data");
    view.setUint32(40, dataSize, true);
    var cursor = 0;
    notes.forEach(function (note) {
      var count = Math.floor(rate * (note.ms / 1000));
      var attack = Math.floor(rate * 0.01);
      var release = Math.floor(rate * 0.06);
      for (var i = 0; i < count; i++) {
        var t = i / rate;
        var env = 1;
        if (i < attack) env = i / attack;
        else if (i > count - release) env = Math.max(0, (count - i) / release);
        var sample = Math.sin(2 * Math.PI * note.freq * t) * (note.gain || 0.2) * env;
        view.setInt16(44 + (cursor + i) * 2, sample * 32767, true);
      }
      cursor += count;
    });
    var bytes = new Uint8Array(buf);
    var binary = "";
    for (var j = 0; j < bytes.length; j++) binary += String.fromCharCode(bytes[j]);
    return "data:audio/wav;base64," + btoa(binary);
  }

  try {
    // Soft doorbell: high then low, quiet.
    DING_WAV = buildToneWav([
      { freq: 784, ms: 140, gain: 0.12 }, // G5
      { freq: 523.25, ms: 220, gain: 0.10 } // C5
    ]);
    // Urgent scan alarm chirp.
    ALARM_WAV = buildToneWav([
      { freq: 880, ms: 90, gain: 0.38 },
      { freq: 660, ms: 70, gain: 0.34 },
      { freq: 880, ms: 110, gain: 0.38 }
    ]);
  } catch (error) {}

  function ensureAudio() {
    var AC = window.AudioContext || window.webkitAudioContext;
    if (AC) {
      if (!audioCtx) audioCtx = new AC();
      if (audioCtx.state === "suspended") audioCtx.resume();
    }
    if (!unlockAudio && DING_WAV) {
      unlockAudio = new Audio(DING_WAV);
      unlockAudio.preload = "auto";
      unlockAudio.volume = 0.01;
    }
    return audioCtx;
  }

  function playWav(url, volume) {
    if (!url) return;
    try {
      var a = new Audio(url);
      a.volume = volume == null ? 1 : volume;
      var play = a.play();
      if (play && play.catch) play.catch(function () {});
    } catch (error) {}
  }

  function dingDong() {
    ensureAudio();
    playWav(DING_WAV, 0.35);
  }

  function beepOnce() {
    ensureAudio();
    playWav(ALARM_WAV, 1);
    try {
      var ctx = audioCtx;
      if (!ctx) return;
      var now = ctx.currentTime;
      [0, 0.14, 0.28].forEach(function (offset, i) {
        var osc = ctx.createOscillator();
        var gain = ctx.createGain();
        osc.type = "square";
        osc.frequency.value = i === 1 ? 660 : 880;
        gain.gain.setValueAtTime(0.0001, now + offset);
        gain.gain.exponentialRampToValueAtTime(0.3, now + offset + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.12);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + offset);
        osc.stop(now + offset + 0.13);
      });
    } catch (error) {}
  }

  function buzz() {
    try {
      if (navigator.vibrate) navigator.vibrate([200, 80, 200, 80, 260]);
    } catch (error) {}
  }

  function setAlertSnap(url) {
    if (!alertSnap || !url) return;
    alertSnap.src = url + (url.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
    alertSnap.hidden = false;
  }

  function showAlert(note, snapUrl) {
    if (alertNote) alertNote.textContent = note || "Nosey bugger.";
    if (snapUrl) setAlertSnap(snapUrl);
    if (alertPanel) {
      alertPanel.hidden = false;
      try { alertPanel.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch (error) {}
    }
    if (alarm) alarm.classList.add("show");
    body.classList.add("alarming");
  }

  function hideAlert() {
    if (alertPanel) alertPanel.hidden = true;
    if (alertSnap) {
      alertSnap.hidden = true;
      alertSnap.removeAttribute("src");
    }
    if (alarm) alarm.classList.remove("show");
    body.classList.remove("alarming");
    if (alarmTimer) {
      clearInterval(alarmTimer);
      alarmTimer = null;
    }
  }

  function startAlarmSound() {
    buzz();
    if (!armed) {
      setStatus("Scan detected — tap Arm alerts for sound");
      return;
    }
    ensureAudio();
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume().then(function () { beepOnce(); }).catch(function () { beepOnce(); });
    } else {
      beepOnce();
    }
    if (alarmTimer) clearInterval(alarmTimer);
    var n = 0;
    alarmTimer = setInterval(function () {
      n += 1;
      buzz();
      beepOnce();
      if (n >= 8) {
        clearInterval(alarmTimer);
        alarmTimer = null;
      }
    }, 700);
  }

  function waitForSnap(ticket) {
    if (!ticket) return;
    var tries = 0;
    function tick() {
      tries += 1;
      var url = "/snap/" + ticket + ".jpg";
      fetch(url + "?t=" + Date.now(), { cache: "no-store" }).then(function (response) {
        if (!response.ok) {
          if (tries < 30) setTimeout(tick, 400);
          return;
        }
        setAlertSnap(url);
      }).catch(function () {
        if (tries < 30) setTimeout(tick, 400);
      });
    }
    tick();
  }

  function onScanned(ticket) {
    var id = ticket || "";
    if (id && id === lastScanNonce) return;
    if (id) lastScanNonce = id;
    showAlert("Nosey bugger.", id ? "/snap/" + id + ".jpg" : "");
    if (id) waitForSnap(id);
    startAlarmSound();
  }

  function onReply(entry) {
    var key = (entry.ts || "") + "|" + (entry.comment || "");
    if (key && key === lastReplyKey) return;
    if (key) lastReplyKey = key;
    addReply(entry, true);
    var ticket = entry.nonce || lastScanNonce || "";
    showAlert(entry.comment || "Nosey bugger.", ticket ? "/snap/" + ticket + ".jpg" : "");
    if (ticket) waitForSnap(ticket);
    startAlarmSound();
    setStatus("New note: " + (entry.comment || ""));
  }

  function playClip(mime, data) {
    try {
      var binary = atob(data);
      var bytes = new Uint8Array(binary.length);
      for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      var blob = new Blob([bytes], { type: mime || "audio/webm" });
      var audio = new Audio(URL.createObjectURL(blob));
      var play = audio.play();
      if (play && play.catch) play.catch(function () {});
    } catch (error) {}
  }

  var reconnectMs = 1000;
  var messagesEl = document.getElementById("messages");

  function formatTime(ts) {
    if (!ts) return "";
    try {
      var d = new Date(ts);
      if (!isNaN(d.getTime())) {
        return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      }
    } catch (error) {}
    return String(ts).replace("T", " ").replace("Z", "");
  }

  function addReply(entry, atTop) {
    if (!messagesEl || !entry || !entry.comment) return false;
    var key = (entry.ts || "") + "|" + entry.comment;
    if (seenComments[key]) return false;
    seenComments[key] = true;
    var empty = messagesEl.querySelector(".empty");
    if (empty) empty.remove();
    var item = document.createElement("li");
    var meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.textContent = formatTime(entry.ts) + (entry.ip ? " · " + entry.ip : "");
    var text = document.createElement("div");
    text.className = "msg-text";
    text.textContent = entry.comment;
    item.appendChild(meta);
    item.appendChild(text);
    if (atTop && messagesEl.firstChild) messagesEl.insertBefore(item, messagesEl.firstChild);
    else messagesEl.appendChild(item);
    return true;
  }

  function loadReplies() {
    if (!messagesEl) return;
    fetch("/replies", { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        messagesEl.innerHTML = "";
        seenComments = {};
        var list = (data && data.replies) || [];
        if (!list.length) {
          var empty = document.createElement("li");
          empty.className = "empty";
          empty.textContent = "No notes yet — waiting for a nosey bugger.";
          messagesEl.appendChild(empty);
          return;
        }
        list.slice().reverse().forEach(function (entry) { addReply(entry, false); });
      })
      .catch(function () {});
  }

  function pollDeskState() {
    fetch("/desk-state", { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (state) {
        if (!state) return;
        if (state.scan && state.scan.nonce) onScanned(state.scan.nonce);
        if (state.reply && state.reply.comment) onReply(state.reply);
        if (state.snap_url && state.scan && state.scan.nonce === lastScanNonce) {
          setAlertSnap(state.snap_url);
        }
        if (!wsOpen && armed) setStatus("Listening for scans (HTTPS poll)");
      })
      .catch(function () {});
  }

  function connect() {
    // :9443 Tailscale Serve breaks websockets — rely on /desk-state polling there.
    if (String(location.port) === "9443" || /:9443$/i.test(location.host)) {
      setStatus(armed ? "Listening for scans (HTTPS poll)" : "Tap Arm alerts, then wait for a scan");
      return;
    }
    setStatus(armed ? "Connecting…" : "Tap Arm alerts, then wait for a scan");
    socket = new WebSocket(proto + "//" + location.host + "/ws");
    socket.addEventListener("open", function () {
      wsOpen = true;
      reconnectMs = 1000;
      socket.send(JSON.stringify({ type: "hello", role: role, nonce: nonce }));
      setStatus(armed ? "Listening for scans" : "Connected — tap Arm alerts for sound");
    });
    socket.addEventListener("message", function (event) {
      var message = {};
      try { message = JSON.parse(event.data); } catch (error) { return; }
      if (message.type === "scanned") onScanned(message.nonce || "");
      if (message.type === "reply") onReply(message);
      if (message.type === "audio") playClip(message.mime, message.data);
    });
    socket.addEventListener("close", function () {
      wsOpen = false;
      setStatus("Disconnected — using poll…");
      var wait = reconnectMs;
      reconnectMs = Math.min(reconnectMs * 1.6, 8000);
      setTimeout(connect, wait);
    });
    socket.addEventListener("error", function () {
      wsOpen = false;
    });
  }

  function refreshTicket() {
    fetch("/ticket", { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (data) { if (data && data.url) draw(data.url); })
      .catch(function () {});
  }

  function pollSnap() {
    var figure = document.querySelector("figure.snap");
    var img = document.getElementById("snap");
    if (!figure || !img) return;
    var ticket = figure.getAttribute("data-nonce") || nonce;
    if (!ticket) return;
    var tries = 0;
    function tick() {
      tries += 1;
      var url = "/snap/" + ticket + ".jpg?t=" + Date.now();
      fetch(url, { cache: "no-store" }).then(function (response) {
        if (!response.ok) {
          if (tries < 25) setTimeout(tick, 400);
          return;
        }
        img.src = url;
        img.hidden = false;
        figure.classList.add("ready");
      }).catch(function () {
        if (tries < 25) setTimeout(tick, 400);
      });
    }
    tick();
  }

  var initial = body.getAttribute("data-qr");
  if (initial) draw(initial);
  if (role === "screen") setInterval(refreshTicket, 45000);
  if (role === "desk") {
    loadReplies();
    setInterval(pollDeskState, 1000);
    pollDeskState();
  }
  if (role === "visitor") pollSnap();

  function armAlerts() {
    armed = true;
    ensureAudio();
    try {
      unlockAudio = new Audio(DING_WAV);
      unlockAudio.volume = 0.01;
      var play = unlockAudio.play();
      if (play && play.then) {
        play.then(function () {
          setTimeout(dingDong, 40);
        }).catch(function () { dingDong(); });
      } else {
        dingDong();
      }
    } catch (error) {
      dingDong();
    }
    if (armBtn) {
      armBtn.textContent = "Alerts armed";
      armBtn.disabled = true;
    }
    if (talk) talk.disabled = false;
    setStatus(
      String(location.port) === "9443"
        ? "Listening for scans (HTTPS poll)"
        : "Listening for scans"
    );
  }

  if (armBtn) {
    armBtn.addEventListener("click", armAlerts);
    armBtn.addEventListener("touchend", function (event) {
      event.preventDefault();
      armAlerts();
    });
  }

  if (alarmDismiss) {
    alarmDismiss.addEventListener("click", hideAlert);
    alarmDismiss.addEventListener("touchend", function (event) {
      event.preventDefault();
      hideAlert();
    });
  }

  if (talk && navigator.mediaDevices) {
    var recording = null;
    var liveStream = null;
    var holding = false;
    var mimeType = "";
    if (window.MediaRecorder) {
      if (MediaRecorder.isTypeSupported("audio/webm")) mimeType = "audio/webm";
      else if (MediaRecorder.isTypeSupported("audio/mp4")) mimeType = "audio/mp4";
    }
    function finishStream() {
      if (!liveStream) return;
      liveStream.getTracks().forEach(function (track) { track.stop(); });
      liveStream = null;
    }
    function release(event) {
      if (event) event.preventDefault();
      holding = false;
      talk.classList.remove("holding");
      if (recording && recording.state === "recording") recording.stop();
      else finishStream();
    }
    function press(event) {
      event.preventDefault();
      ensureAudio();
      if (holding) return;
      holding = true;
      talk.classList.add("holding");
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        if (!holding) {
          stream.getTracks().forEach(function (track) { track.stop(); });
          return;
        }
        liveStream = stream;
        recording = mimeType ? new MediaRecorder(stream, { mimeType: mimeType }) : new MediaRecorder(stream);
        var chunks = [];
        recording.ondataavailable = function (piece) { if (piece.data.size) chunks.push(piece.data); };
        recording.onstop = function () {
          finishStream();
          var blob = new Blob(chunks, { type: recording.mimeType || mimeType || "audio/mp4" });
          if (!blob.size) return;
          var reader = new FileReader();
          reader.onload = function () {
            var text = String(reader.result || "");
            var data = text.split(",")[1] || "";
            if (socket && socket.readyState === 1 && data) {
              socket.send(JSON.stringify({ type: "audio", mime: blob.type, data: data }));
            }
          };
          reader.readAsDataURL(blob);
        };
        recording.start();
      }).catch(function () {
        holding = false;
        talk.classList.remove("holding");
      });
    }
    talk.addEventListener("touchstart", press, { passive: false });
    talk.addEventListener("touchend", release);
    talk.addEventListener("touchcancel", release);
    talk.addEventListener("mousedown", press);
    talk.addEventListener("mouseup", release);
    talk.addEventListener("contextmenu", function (event) { event.preventDefault(); });
  }

  connect();
})();
