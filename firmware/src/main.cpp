/*
 * Claude Usage Ring — firmware per D1 mini (ESP8266) + GC9A01 240x240
 * -------------------------------------------------------------------
 * Legge  http://<host>:<porta>/claude  sulla LAN e disegna:
 *   - anello di traccia + arco di avanzamento (arancione)
 *   - percentuale della finestra a 7 giorni al centro
 *   - orario del prossimo reset e countdown sotto
 *
 * Il micro NON ha credenziali: fa solo una GET in chiaro sulla LAN.
 *
 * Geometria e palette sono 1:1 con docs/wiring.md (spazio 240x240).
 * Niente framebuffer: su ESP8266 non ci sta (115 KB di RAM su ~40 KB liberi),
 * quindi si disegnano primitive e si ridisegna solo il delta.
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <TFT_eSPI.h>
#include <math.h>
#include <time.h>

#include "config.h"   // NON committato: vedi include/config.h.example

// ---------------------------------------------------------------- geometria
static const int16_t CX = 120, CY = 120;
static const int16_t R_RING  = 103;   // mezzeria dell'anello
static const int16_t RING_W  = 14;    // spessore dell'anello
static const int16_t Y_LABEL = 62;    // etichetta "7g"
static const int16_t Y_PCT   = 118;   // percentuale (alzata a richiesta)
static const int16_t Y_RESET = 169;   // orario di reset
static const int16_t Y_CDOWN = 191;   // countdown
static const int16_t PCT_OVER = 80;   // oltre questa soglia l'arco cambia tinta

static const float DEG2RAD = 0.0174532925f;

// ---------------------------------------------------------------- palette
constexpr uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) {
  return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}
constexpr uint16_t C_BG     = rgb565(0x0e, 0x0e, 0x11);
constexpr uint16_t C_TRACK  = rgb565(0x2b, 0x2b, 0x33);
constexpr uint16_t C_ARC    = rgb565(0xd9, 0x77, 0x57);
constexpr uint16_t C_ARC_HI = rgb565(0xe0, 0x5a, 0x3a);
constexpr uint16_t C_TEXT   = 0xFFFF;                  // bianco puro: leggibilita' massima
constexpr uint16_t C_DIM    = 0xFFFF;                  // alias: anche il testo secondario e' bianco
constexpr uint16_t C_OFF    = rgb565(0x8a, 0x8a, 0x94);  // solo per lo stato offline

TFT_eSPI tft = TFT_eSPI();

// ---------------------------------------------------------------- stato
struct Usage {
  bool  ok       = false;   // dato utilizzabile
  bool  stale    = false;   // dato vecchio
  float pct      = -1;      // finestra 7 giorni
  long  resetSec = -1;      // secondi al reset della finestra 7 giorni
  char  err[48]  = "";
  unsigned long millisAtFetch = 0;
};

static Usage   usage;
static float   drawnAngle = -1;      // arco disegnato finora (gradi)
static uint16_t drawnColor = C_ARC;  // tinta usata per l'arco disegnato
static int     lastState = -1;       // 0 = online, 1 = offline
static unsigned long lastPoll = 0, lastCountdown = 0;
static bool    timeSynced = false;

// ---------------------------------------------------------------- disegno
static inline void arcPoint(float deg, float r, int16_t &x, int16_t &y) {
  float rad = deg * DEG2RAD;
  x = (int16_t)lroundf(CX + r * sinf(rad));
  y = (int16_t)lroundf(CY - r * cosf(rad));
}

// banda circolare fra due angoli (0 = ore 12, senso orario), estremi tondi
static void drawBand(float from, float to, uint16_t color) {
  if (to <= from) return;
  float arcPx = (to - from) * R_RING * DEG2RAD;
  int   steps = (int)ceilf(arcPx / 3.0f);
  if (steps < 1) steps = 1;
  for (int i = 0; i <= steps; i++) {
    float a = from + (to - from) * (float)i / (float)steps;
    int16_t x, y;
    arcPoint(a, R_RING, x, y);
    tft.fillCircle(x, y, RING_W / 2, color);
  }
}

static void drawTrack() { drawBand(0, 360, C_TRACK); }

// arco di avanzamento ridisegnando solo il delta
static void drawArc(float target, uint16_t color) {
  if (target < 0) target = 0;
  if (target > 360) target = 360;
  if (drawnAngle < 0) {          // primo disegno: traccia + arco
    drawTrack();
    drawnAngle = 0;
    drawnColor = color;
  }
  if (color != drawnColor) {     // cambio di soglia: rifaccio l'arco da capo
    if (drawnAngle > 0) drawBand(0, drawnAngle + 2, C_TRACK);
    drawnAngle = 0;
    drawnColor = color;
  }
  if (target > drawnAngle) {
    drawBand(drawnAngle, target, color);
    drawnAngle = target;
  } else if (target < drawnAngle) {   // reset della finestra: cancello e ridisegno
    drawBand(target, drawnAngle + 2, C_TRACK);
    drawBand(0, target, color);
    drawnAngle = target;
  }
}

static void textAt(const char *s, int16_t y, const GFXfont *font, uint8_t size,
                   uint16_t color, uint16_t bg) {
  tft.setFreeFont(font);
  tft.setTextSize(size);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(color, bg);
  // ATTENZIONE: il numero di font DEVE essere 1. In TFT_eSPI il ramo "free font" e'
  //   bool freeFont = (font == 1 && gfxFont);
  // quindi con 0 la libreria legge la tabella dei font bitmap all'indice 0 (vuota) e non
  // disegna NULLA, senza errori di compilazione. Con 1 usa il GFXfont di setFreeFont().
  tft.drawString(s, CX, y, 1);
}

static void fmtCountdown(long sec, char *out, size_t n) {
  if (sec < 0)      { snprintf(out, n, "--"); return; }
  if (sec >= 3600)  { snprintf(out, n, "%ldh %02ldm", sec / 3600, (sec % 3600) / 60); }
  else              { snprintf(out, n, "%ldm", sec / 60); }
}

static void fmtResetClock(long sec, char *out, size_t n) {
  if (!timeSynced || sec < 0) { snprintf(out, n, "reset --:--"); return; }
  time_t t = time(nullptr) + sec;
  struct tm tmv;
  localtime_r(&t, &tmv);
  snprintf(out, n, "reset %02d:%02d", tmv.tm_hour, tmv.tm_min);
}

// quadrante online
static void drawOnline(bool full) {
  int pct = (int)lroundf(usage.pct);
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  uint16_t color = (pct > PCT_OVER) ? C_ARC_HI : C_ARC;

  if (full || lastState != 0) {
    tft.fillScreen(C_BG);
    drawTrack();
    drawnAngle = 0;
    drawnColor = color;
    textAt("7g", Y_LABEL, &FreeSansBold12pt7b, 1, C_TEXT, C_BG);
    pct = (int)lroundf(usage.pct);
  }
  drawArc(3.6f * (float)pct, color);

  char buf[24];
  snprintf(buf, sizeof(buf), "%d%%", pct);
  textAt(buf, Y_PCT, &FreeSansBold24pt7b, 1, C_TEXT, C_BG);

  fmtResetClock(usage.resetSec, buf, sizeof(buf));
  textAt(buf, Y_RESET, &FreeSansBold9pt7b, 1, C_TEXT, C_BG);

  char cd[16];
  fmtCountdown(usage.resetSec, cd, sizeof(cd));
  textAt(cd, Y_CDOWN, &FreeSans9pt7b, 1, C_DIM, C_BG);

  lastState = 0;
}

// quadrante offline: anello grigio e "--"
static void drawOffline() {
  if (lastState == 1) return;
  tft.fillScreen(C_BG);
  drawBand(0, 360, C_OFF);
  drawnAngle = 0;
  drawnColor = C_ARC;
  textAt("7g", Y_LABEL, &FreeSansBold12pt7b, 1, C_TEXT, C_BG);
  textAt("--", Y_PCT, &FreeSansBold24pt7b, 1, C_TEXT, C_BG);
  textAt(usage.err[0] ? usage.err : "offline", Y_RESET, &FreeSans9pt7b, 1, C_TEXT, C_BG);
  // (font 9pt a size 1: le righe di servizio restano piccole per scelta)
  lastState = 1;
}

// ---------------------------------------------------------------- rete
static bool jsonNumber(const String &body, const char *key, float &out) {
  String pat = String('"') + key + "\":";
  int i = body.indexOf(pat);
  if (i < 0) return false;
  int j = i + pat.length();
  if (body.startsWith("null", j)) return false;
  out = body.substring(j).toFloat();
  return true;
}

static bool wifiUp() {
  if (WiFi.status() == WL_CONNECTED) return true;
  Serial.printf("[wifi] riconnessione a %s\n", WIFI_SSID);
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[wifi] ok, ip %s\n", WiFi.localIP().toString().c_str());
    return true;
  }
  Serial.println("[wifi] non connesso");
  return false;
}

static void pollUsage() {
  if (!wifiUp()) {
    usage.ok = false; usage.stale = true;
    snprintf(usage.err, sizeof(usage.err), "wifi assente");
    drawOffline();
    return;
  }
  WiFiClient client;
  HTTPClient http;
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%d%s", RING_HOST, RING_PORT, RING_PATH);
  http.setTimeout(4000);
  http.setReuse(false);
  if (!http.begin(client, url)) {
    snprintf(usage.err, sizeof(usage.err), "url non valido");
    return;
  }
  int code = http.GET();
  if (code != 200) {
    snprintf(usage.err, sizeof(usage.err), "http %d", code);
    usage.ok = false; usage.stale = true;
    http.end();
    drawOffline();
    return;
  }
  String body = http.getString();
  http.end();
  Serial.printf("[poll] %s\n", body.c_str());

  float v, r, age, stale;
  bool hasPct = jsonNumber(body, "p7", v);   // finestra 7 giorni
  bool hasOk  = jsonNumber(body, "ok", stale);
  bool hasSt  = jsonNumber(body, "stale", stale);
  (void)hasOk;

  usage.ok    = hasPct && v >= 0 && !(hasSt && stale >= 0.5f);
  usage.stale = hasSt && stale >= 0.5f;
  if (hasPct) usage.pct  = v;
  if (jsonNumber(body, "r7", r))   usage.resetSec = (long)r;
  (void)age;

  if (usage.ok) {
    usage.millisAtFetch = millis();
    usage.err[0] = '\0';
    drawOnline(lastState != 0);
  } else {
    drawOffline();
  }
}

// ---------------------------------------------------------------- setup
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[Claude Usage Ring] avvio");

  tft.init();
  tft.setRotation(0);
  tft.fillScreen(C_BG);
  drawTrack();
  textAt("Claude usage", 108, &FreeSansBold12pt7b, 1, C_TEXT, C_BG);
  textAt("connessione...", 140, &FreeSans9pt7b, 1, C_TEXT, C_BG);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  wifiUp();

  configTime(TZ_INFO, "pool.ntp.org", "time.cloudflare.com");
  struct tm tmv;
  timeSynced = getLocalTime(&tmv, 5000);
  Serial.printf("[ntp] orario %s\n", timeSynced ? "sincronizzato" : "non disponibile");

  pollUsage();
  lastPoll = lastCountdown = millis();
}

void loop() {
  unsigned long now = millis();

  if (now - lastPoll >= (unsigned long)POLL_SECONDS * 1000UL) {
    lastPoll = now;
    pollUsage();
  }

  // countdown fra un poll e l'altro, senza rileggere il server
  if (lastState == 0 && usage.resetSec >= 0 && now - lastCountdown >= 20000UL) {
    lastCountdown = now;
    long elapsed = (long)((now - usage.millisAtFetch) / 1000UL);
    long left = usage.resetSec - elapsed;
    if (left < 0) left = 0;
    char cd[16];
    fmtCountdown(left, cd, sizeof(cd));
    textAt(cd, Y_CDOWN, &FreeSans9pt7b, 1, C_DIM, C_BG);
    char rz[24];
    fmtResetClock(left, rz, sizeof(rz));
    textAt(rz, Y_RESET, &FreeSansBold9pt7b, 1, C_TEXT, C_BG);
  }

  delay(200);
}
