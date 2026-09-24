import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "wizwam.omanosey"
  ipcTarget: "wizwam.omanosey"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property bool idleOn: Model.boolSetting(settings, "idle", true)

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: {
    if (opened) nosey.refresh()
  }

  function persistSetting(key, value) {
    var entry = { id: root.moduleName }
    for (var name in settings) if (name !== "id") entry[name] = settings[name]
    entry[key] = value
    root.settings = entry
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
    nosey.settings = entry
    nosey.persistConfig()
  }

  Service {
    id: nosey
    settings: root.settings
    shell: root.bar ? root.bar.shell : null
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function preview(): string { nosey.preview(); return "ok" }
    function status(): string { return nosey.statusText }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    tooltipText: root.idleOn ? "OmaNosey screensaver on" : "OmaNosey screensaver off"
    iconComponent: Component {
      Item {
        Text {
          anchors.centerIn: parent
          text: "QR"
          color: root.idleOn ? (root.bar ? root.bar.foreground : root.foreground) : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) nosey.preview()
      else if (buttonCode === Qt.MiddleButton) root.persistSetting("idle", !root.idleOn)
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(420))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      Column {
        id: column
        width: parent.width
        spacing: Style.space(12)

        Text {
          width: parent.width
          text: "OmaNosey"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }

        Text {
          width: parent.width
          text: nosey.statusText
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
        }

        Text {
          visible: nosey.lastError !== ""
          width: parent.width
          text: nosey.lastError
          color: root.bar && root.bar.urgent ? root.bar.urgent : root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Row {
          spacing: Style.space(8)
          Text {
            text: root.idleOn ? "Idle screensaver: on" : "Idle screensaver: off"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }
        }

        Item {
          width: parent.width
          height: idleHit.implicitHeight
          Text {
            id: idleHit
            text: root.idleOn ? "Turn off (restore previous screensaver)" : "Turn on (Nosey on idle)"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.persistSetting("idle", !root.idleOn)
          }
        }

        Item {
          width: parent.width
          height: previewHit.implicitHeight
          Text {
            id: previewHit
            text: "Preview now"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
          }
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: nosey.preview()
          }
        }

        Item {
          width: parent.width
          height: debugHit.implicitHeight
          Text {
            id: debugHit
            text: "Debug preview (hold open)"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
          }
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: nosey.debugPreview()
          }
        }

        Text {
          visible: nosey.actionStatus !== ""
          width: parent.width
          text: nosey.actionStatus
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          text: nosey.debugLog !== "" ? ("Debug log: " + nosey.debugLog) : "Debug log appears after the screensaver starts."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Text {
          visible: nosey.lastEvents.length > 0
          width: parent.width
          text: nosey.lastEvents.join("\n")
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WrapAnywhere
        }

        Text {
          width: parent.width
          text: nosey.publicLive
            ? ("Kiosk: " + nosey.kioskUrl)
            : ("QR uses http://" + nosey.lanIp + ":" + nosey.port + "/ on this LAN. Public URL is not serving Nosey yet.")
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          text: "Right-click the chip to preview. Debug preview holds the screen until Esc and logs what would have dismissed it. Middle-click toggles idle. Any key or mouse movement dismisses a normal preview."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
