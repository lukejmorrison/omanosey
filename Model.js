function setting(settings, name, fallback) {
  var value = settings ? settings[name] : undefined
  return value === undefined || value === null ? fallback : value
}

function boolSetting(settings, name, fallback) {
  var value = setting(settings, name, fallback)
  if (value === true || value === "true") return true
  if (value === false || value === "false") return false
  return fallback
}

function intSetting(settings, name, fallback, min, max) {
  var n = parseInt(String(setting(settings, name, fallback)), 10)
  if (!isFinite(n)) n = fallback
  if (n < min) n = min
  if (n > max) n = max
  return n
}

function parseStatus(raw) {
  try {
    var data = JSON.parse(String(raw || "{}"))
    if (!data || typeof data !== "object") return { ok: false, lastError: "bad status" }
    return {
      ok: data.ok !== false,
      idle: data.idle === true,
      publicUrl: data.public_url || "",
      publicLive: data.public_live === true,
      kioskUrl: data.kiosk_url || "",
      local: data.local === true,
      port: data.port || 8765,
      lanIp: data.lan_ip || "",
      debugLog: data.debug_log || "",
      lastEvents: Array.isArray(data.last_events) ? data.last_events : [],
      lastError: data.lastError || ""
    }
  } catch (error) {
    return { ok: false, lastError: String(error) }
  }
}

if (typeof module !== "undefined") {
  module.exports = {
    setting: setting,
    boolSetting: boolSetting,
    intSetting: intSetting,
    parseStatus: parseStatus
  }
}
