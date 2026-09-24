import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "Model.js" as Model

Item {
  id: root

  property var settings: ({})
  property var shell: null
  property var pluginRegistry: null

  property bool idle: true
  property bool local: false
  property bool publicLive: false
  property string publicUrl: ""
  property string kioskUrl: ""
  property string lanIp: ""
  property int port: 8765
  property string statusText: "Checking…"
  property string lastError: ""
  property string actionStatus: ""
  property string debugLog: ""
  property var lastEvents: []

  readonly property string helperPath: resolvedHelper()
  readonly property string python: "/usr/bin/python3"
  readonly property string installPath: resolvedInstall()
  readonly property int refreshIntervalSec: 8

  property string _statusOutput: ""
  property string _statusError: ""

  function resolvedHelper() {
    var url = String(Qt.resolvedUrl("./backend/server.py"))
    if (url.indexOf("file://") === 0) url = url.substring(7)
    return url
  }

  function resolvedInstall() {
    var url = String(Qt.resolvedUrl("./scripts/install-screensaver.sh"))
    if (url.indexOf("file://") === 0) url = url.substring(7)
    return url
  }

  function persistConfig() {
    if (helperPath === "" || configProcess.running) return
    var idleFlag = Model.boolSetting(settings, "idle", true) ? "true" : "false"
    var url = String(Model.setting(settings, "publicUrl", "https://e1.yahvehyireh.com"))
    var p = String(Model.intSetting(settings, "port", 8765, 1024, 65535))
    configProcess.command = [python, helperPath, "set", "--idle", idleFlag, "--public-url", url, "--port", p]
    configProcess.running = true
  }

  function refresh() {
    if (statusProcess.running || helperPath === "") return
    _statusOutput = ""
    _statusError = ""
    statusProcess.command = [python, helperPath, "status"]
    statusProcess.running = true
  }

  function applyStatus(raw) {
    var parsed = Model.parseStatus(raw)
    if (!parsed.ok && parsed.lastError) {
      lastError = parsed.lastError
      statusText = "Nosey unavailable"
      return
    }
    lastError = ""
    idle = parsed.idle
    local = parsed.local
    publicLive = parsed.publicLive
    publicUrl = parsed.publicUrl
    kioskUrl = parsed.kioskUrl
    lanIp = parsed.lanIp
    port = parsed.port
    debugLog = parsed.debugLog || ""
    lastEvents = parsed.lastEvents || []
    if (publicLive) statusText = "Public Nosey live"
    else if (local) statusText = "Local honeypot on " + lanIp + ":" + port
    else statusText = "Starting local honeypot…"
  }

  function preview() {
    launchScreensaver(false)
  }

  function debugPreview() {
    launchScreensaver(true)
  }

  function launchScreensaver(debugHold) {
    if (previewProcess.running) return
    actionStatus = debugHold ? "Debug preview…" : "Previewing…"
    var command = debugHold ? "omarchy-launch-screensaver force debug" : "omarchy-launch-screensaver force"
    previewProcess.command = ["bash", "-lc", command]
    previewProcess.running = true
  }

  function ensureServer() {
    if (serveProcess.running || helperPath === "") return
    serveProcess.command = [python, helperPath, "serve"]
    serveProcess.running = true
  }

  function ensureDispatcher() {
    if (installProcess.running || installPath === "") return
    installProcess.command = ["bash", installPath]
    installProcess.running = true
  }

  Process {
    id: statusProcess
    stdout: SplitParser {
      onRead: function(line) { root._statusOutput += line + "\n" }
    }
    stderr: SplitParser {
      onRead: function(line) { root._statusError += line + "\n" }
    }
    onExited: function() {
      var raw = root._statusOutput.trim()
      if (raw !== "") root.applyStatus(raw)
      else if (root._statusError.trim() !== "") root.lastError = root._statusError.trim()
    }
  }

  Process {
    id: configProcess
    onExited: function() { root.ensureDispatcher(); root.refresh() }
  }

  Process {
    id: serveProcess
    onExited: function(code) { if (code !== 0) root.lastError = "Local Nosey server exited" }
  }

  Process {
    id: installProcess
    onExited: function() { root.refresh() }
  }

  Process {
    id: previewProcess
    onExited: function() { root.actionStatus = ""; root.refresh() }
  }

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Component.onCompleted: {
    root.persistConfig()
    root.ensureServer()
    root.ensureDispatcher()
    root.refresh()
  }
}
