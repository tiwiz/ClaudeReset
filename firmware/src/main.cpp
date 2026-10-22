/*
 * Claude Usage Ring — firmware per D1 mini (ESP8266) + GC9A01 240x240
 * -------------------------------------------------------------------
 * Scopre il servizio da solo via mDNS (_claudereset._tcp): IP e porta arrivano
 * dall'annuncio, quindi il servizio può traslocare senza riflashare. Poi legge
 * http://<scoperto>:<porta>/api/usage e disegna:
 *   - anello di traccia + arco di avanzamento (arancione)
 *   - percentuale della finestra a 7 giorni al centro
 *   - orario del prossimo reset e countdown sotto
 *
 * Il micro NON ha credenziali di servizio: fa solo una GET in chiaro sulla LAN. Le uniche
 * credenziali che tocca sono quelle del wifi, che gli arrivano dal browser via Improv
 * (immagine del flasher) o da config.h (build locale).
 *
 * Geometria e palette sono 1:1 con docs/wiring.md (spazio 240x240).
 * Niente framebuffer: su ESP8266 non ci sta (115 KB di RAM su ~40 KB liberi),
 * quindi si disegnano primitive e si ridisegna solo il delta.
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266mDNS.h>
#include <WiFiClient.h>
#include <TFT_eSPI.h>
#include <ImprovWiFiLibrary.h>
#include <EEPROM.h>
#include <math.h>
#include <time.h>

// config.h è locale e gitignorato (wifi, e volendo i nomi): se c'è, i suoi valori
// vincono sui default. L'immagine pubblica del flasher si compila senza
// (CLAUDE_RING_PUBLIC_BUILD), quindi non contiene nessun segreto: lì la rete arriva
// dal browser via Improv.
#if !defined(CLAUDE_RING_PUBLIC_BUILD) && __has_include("config.h")
#include "config.h"
#endif
#include "config_defaults.h"

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
  float pct7     = -1;      // finestra 7 giorni
  long  reset7   = -1;      // secondi al reset della finestra 7 giorni
  float pct5     = -1;      // finestra 5 ore
  long  reset5   = -1;
  char  err[48]  = "";
  unsigned long millisAtFetch = 0;
};

static Usage   usage;
static float   drawnAngle = -1;      // arco disegnato finora (gradi)
static uint16_t drawnColor = C_ARC;  // tinta usata per l'arco disegnato
static int     lastState = -1;       // 0 = online, 1 = offline
static unsigned long lastPoll = 0, lastCountdown = 0;
static bool    timeSynced = false;

// ---------------------------------------------------------------- quale finestra
// Il servizio manda ENTRAMBE le finestre nello stesso JSON: cambiare vista non costa
// né una richiesta né un'attesa, è solo la scelta di cosa disegnare.
static uint8_t view = 0;                       // 0 = 7 giorni, 1 = 5 ore
static float viewPct()         { return view ? usage.pct5 : usage.pct7; }
static long  viewReset()       { return view ? usage.reset5 : usage.reset7; }
static const char *viewLabel() { return view ? "5h" : "7g"; }

// ---------------------------------------------------------------- credenziali di rete
// Il browser le consegna via Improv (protocollo seriale) e qui finiscono in EEPROM,
// così sopravvivono al riavvio. Se non ce ne sono, si usa config.h quando presente.
struct StoredCreds {
  uint32_t magic;
  char     ssid[33];
  char     pass[65];
  uint8_t  view;      // quale finestra stava mostrando (0 = 7 giorni, 1 = 5 ore)
};
static const uint32_t CREDS_MAGIC = 0x434C5231;   // "CLR1"
static StoredCreds creds;
static ImprovWiFi  improvSerial(&Serial);

static void saveCreds(const char *ssid, const char *password) {
  creds.magic = CREDS_MAGIC;
  strncpy(creds.ssid, ssid, sizeof(creds.ssid) - 1);
  creds.ssid[sizeof(creds.ssid) - 1] = '\0';
  strncpy(creds.pass, password, sizeof(creds.pass) - 1);
  creds.pass[sizeof(creds.pass) - 1] = '\0';
  EEPROM.put(0, creds);
  EEPROM.commit();
  Serial.println("[improv] credenziali salvate in EEPROM");
}

static void onImprovConnected(const char *ssid, const char *password) {
  saveCreds(ssid, password);
}

static void onImprovError(ImprovTypes::Error err) {
  Serial.printf("[improv] errore %d\n", (int)err);
}

static void loadCreds() {
  EEPROM.begin(sizeof(StoredCreds));
  EEPROM.get(0, creds);
  if (creds.magic != CREDS_MAGIC) {
    creds.magic = 0;
    creds.ssid[0] = '\0';
    creds.pass[0] = '\0';
  }
  if (creds.view > 1) creds.view = 0;   // prima di questa versione non c'era
  if (creds.ssid[0] == '\0' && WIFI_SSID[0] != '\0') {
    strncpy(creds.ssid, WIFI_SSID, sizeof(creds.ssid) - 1);
    strncpy(creds.pass, WIFI_PASS, sizeof(creds.pass) - 1);
    Serial.println("[wifi] uso le credenziali di config.h");
  }
}

// ---------------------------------------------------------------- servizio via mDNS
// Il servizio si annuncia come _claudereset._tcp: l'annuncio porta con sé indirizzo e
// porta, quindi il firmware non ha bisogno di sapere dove sta. L'IP in config.h serve
// solo da ripiego se in rete nessuno risponde all'annuncio.
static IPAddress svcIp;
static uint16_t  svcPort = SERVICE_PORT;
static bool      svcDiscovered = false;   // l'indirizzo corrente viene dall'annuncio
static int       failStreak = 0;
static int       pollsSinceFallback = 0;  // quanti giri sto andando con l'indirizzo di ripiego

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

// Cosa c'è già a schermo. Riscrivere un testo identico è lavoro inutile e si vede:
// TFT_eSPI ridisegna il rettangolo del testo, e a 27 MHz di SPI la passata si nota.
static char shownLabel[8] = "";
static char shownPct[16] = "";
static char shownReset[24] = "";
static char shownCountdown[16] = "";

static void textIfChanged(const char *s, int16_t y, const GFXfont *font, uint8_t size,
                          uint16_t color, char *cache, size_t cacheSize) {
  if (strncmp(cache, s, cacheSize) == 0) return;
  snprintf(cache, cacheSize, "%s", s);
  textAt(s, y, font, size, color, C_BG);
}

static void forgetShownText() {
  shownLabel[0] = shownPct[0] = shownReset[0] = shownCountdown[0] = '\0';
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
  int pct = (int)lroundf(viewPct());
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  uint16_t color = (pct > PCT_OVER) ? C_ARC_HI : C_ARC;

  if (full || lastState != 0) {
    tft.fillScreen(C_BG);
    drawTrack();
    drawnAngle = 0;
    drawnColor = color;
    forgetShownText();   // schermo pulito: i testi vanno riscritti tutti
  }
  drawArc(3.6f * (float)pct, color);

  // I testi vengono dopo l'anello: se si disegnassero prima, durante il ridisegno
  // completo si vedrebbe la label "7g" da sola sul fondo, prima del resto.
  char buf[24];
  textIfChanged(viewLabel(), Y_LABEL, &FreeSansBold12pt7b, 1, C_TEXT, shownLabel, sizeof(shownLabel));
  snprintf(buf, sizeof(buf), "%d%%", pct);
  textIfChanged(buf, Y_PCT, &FreeSansBold24pt7b, 1, C_TEXT, shownPct, sizeof(shownPct));

  fmtResetClock(viewReset(), buf, sizeof(buf));
  textIfChanged(buf, Y_RESET, &FreeSansBold9pt7b, 1, C_TEXT, shownReset, sizeof(shownReset));

  char cd[16];
  fmtCountdown(viewReset(), cd, sizeof(cd));
  textIfChanged(cd, Y_CDOWN, &FreeSans9pt7b, 1, C_TEXT, shownCountdown, sizeof(shownCountdown));

  lastState = 0;
}

// quadrante offline: anello grigio, "--" e il motivo in chiaro
static void drawOffline() {
  if (lastState == 1) return;
  tft.fillScreen(C_BG);
  drawBand(0, 360, C_OFF);
  drawnAngle = 0;
  drawnColor = C_ARC;
  forgetShownText();   // lo schermo è stato azzerato: niente di ciò che era scritto vale più
  textAt(viewLabel(), Y_LABEL, &FreeSansBold12pt7b, 1, C_TEXT, C_BG);
  textAt("--", Y_PCT, &FreeSansBold24pt7b, 1, C_TEXT, C_BG);
  // Il motivo sta sulla riga del reset, tagliato per stare dentro la corda del cerchio
  // a quella altezza. Meglio dire "non autenticato" che ripetere l'ultimo numero.
  char reason[26];
  snprintf(reason, sizeof(reason), "%.24s", usage.err[0] ? usage.err : "offline");
  textAt(reason, Y_RESET, &FreeSans9pt7b, 1, C_TEXT, C_BG);
  // (font 9pt a size 1: le righe di servizio restano piccole per scelta)
  lastState = 1;
}

// ---------------------------------------------------------------- pulsante
// Un contatto momentaneo fra D0 (GPIO16) e 3V3: a riposo il pull-down interno lo tiene
// basso, premuto legge alto. Nessuna resistenza esterna. Il cambio avviene sull'istante
// della pressione, dopo BUTTON_DEBOUNCE_MS di livello stabile (i contatti rimbalzano).
static bool buttonStable = false, buttonCandidate = false;
static unsigned long buttonCandidateAt = 0;

static void toggleView() {
  view = view ? 0 : 1;
  creds.view = view;
  EEPROM.put(0, creds);          // la scelta sopravvive al riavvio
  EEPROM.commit();
  Serial.printf("[vista] %s\n", viewLabel());
  lastState = -1;                // forza il ridisegno completo dell'anello
  drawnAngle = -1;
  forgetShownText();
  if (usage.ok) drawOnline(true);
  else drawOffline();
}

static void pollButton() {
#if BUTTON_PIN >= 0
  bool now = (digitalRead(BUTTON_PIN) == HIGH);
  if (now != buttonCandidate) {       // livello cambiato: aspetto che si stabilizzi
    buttonCandidate = now;
    buttonCandidateAt = millis();
    return;
  }
  if (buttonCandidate != buttonStable && millis() - buttonCandidateAt >= BUTTON_DEBOUNCE_MS) {
    buttonStable = buttonCandidate;
    if (buttonStable) toggleView();
  }
#endif
}

// ---------------------------------------------------------------- rete
// Il JSON del servizio arriva da json.dumps, che mette SEMPRE uno spazio dopo i due punti
// ("r": null, "err": ""): dopo i due punti gli spazi vanno saltati, altrimenti il controllo
// di "null" non scatta e toFloat() legge 0 — e un reset a 0 è "l'ora corrente".
static int skipSpaces(const String &body, int j) {
  while (j < (int)body.length() && (body[j] == ' ' || body[j] == '\t')) j++;
  return j;
}

static bool jsonNumber(const String &body, const char *key, float &out) {
  String pat = String('"') + key + "\":";
  int i = body.indexOf(pat);
  if (i < 0) return false;
  int j = skipSpaces(body, i + pat.length());
  if (body.startsWith("null", j)) return false;
  out = body.substring(j).toFloat();
  return true;
}

static bool jsonString(const String &body, const char *key, char *out, size_t n) {
  String pat = String('"') + key + "\":";
  int i = body.indexOf(pat);
  if (i < 0) return false;
  int j = skipSpaces(body, i + pat.length());
  if (j >= (int)body.length() || body[j] != '"') return false;
  j++;
  int k = body.indexOf('"', j);
  if (k < 0) return false;
  String s = body.substring(j, k);
  strncpy(out, s.c_str(), n - 1);
  out[n - 1] = '\0';
  return true;
}

static bool wifiUp() {
  if (WiFi.status() == WL_CONNECTED) return true;
  if (creds.ssid[0] == '\0') {
    Serial.println("[wifi] nessuna rete configurata: passare dal flasher (Improv)");
    return false;
  }
  Serial.printf("[wifi] riconnessione a %s\n", creds.ssid);
  WiFi.disconnect();
  WiFi.begin(creds.ssid, creds.pass);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[wifi] ok, ip %s\n", WiFi.localIP().toString().c_str());
    return true;
  }
  Serial.println("[wifi] non connesso");
  return false;
}

// Chiede chi offre il servizio. Blocca al massimo ~3 s, quindi si chiama solo quando
// serve: all'avvio, e dopo una serie di errori (il servizio può essere traslocato).
static bool discoverService(bool loud) {
  uint32_t answers = MDNS.queryService(MDNS_SERVICE, "tcp", 3000);
  for (uint32_t i = 0; i < answers; i++) {
    IPAddress ip  = MDNS.answerIP(i);
    uint16_t  port = MDNS.answerPort(i);
    if (ip.isSet() && port) {
      svcIp = ip;
      svcPort = port;
      svcDiscovered = true;
      MDNS.removeQuery();
      if (loud) {
        Serial.printf("[mdns] %s trovato su %s:%u\n", MDNS_SERVICE,
                      svcIp.toString().c_str(), (unsigned)svcPort);
      }
      return true;
    }
  }
  MDNS.removeQuery();
  svcDiscovered = false;
  if (!svcIp.isSet()) {
    svcIp.fromString(FALLBACK_HOST);
    svcPort = SERVICE_PORT;
    if (loud) {
      Serial.printf("[mdns] nessun annuncio, per ora uso %s:%u\n", FALLBACK_HOST,
                    (unsigned)svcPort);
    }
  }
  return false;   // false = nessun annuncio trovato, anche se un indirizzo c'è
}

// La query può cadere nel momento sbagliato (responder non ancora pronto): si riprova
// qualche volta, dando respiro a MDNS.update() fra un tentativo e l'altro.
static bool discoverWithRetries(int attempts) {
  for (int i = 0; i < attempts; i++) {
    if (discoverService(i == 0)) return true;
    for (int k = 0; k < 20; k++) {
      MDNS.update();
      delay(50);
    }
  }
  Serial.println("[mdns] nessuna risposta agli annunci: vado avanti con l'indirizzo di ripiego");
  return false;
}

static void pollUsage() {
  if (!wifiUp()) {
    usage.ok = false; usage.stale = true;
    snprintf(usage.err, sizeof(usage.err), creds.ssid[0] ? "wifi assente" : "configura il wifi");
    drawOffline();
    return;
  }
  if (!svcIp.isSet()) {
    discoverWithRetries(2);
  } else if (!svcDiscovered && ++pollsSinceFallback >= 5) {
    // Sto usando l'indirizzo di ripiego: riprovo ogni 5 giri, così non pago 3 s di
    // attesa a ogni lettura se in rete l'annuncio proprio non passa.
    pollsSinceFallback = 0;
    if (discoverService(false)) pollsSinceFallback = 0;
  }

  WiFiClient client;
  HTTPClient http;
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u%s", svcIp.toString().c_str(),
           (unsigned)svcPort, SERVICE_PATH);
#if defined(TEST_USAGE_URL)
  // Banco: leggi da un payload finto invece che dal servizio vero, per vedere cosa fa il
  // quadrante con dati che in natura non capitano (arco alto, finestra vuota, errore).
  snprintf(url, sizeof(url), "%s", TEST_USAGE_URL);
#endif
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
    // Tre errori di fila: probabilmente il servizio non sta più dove l'avevo trovato.
    if (++failStreak >= 3) {
      failStreak = 0;
      Serial.println("[mdns] tre errori di fila: riscoperta del servizio");
      if (svcDiscovered) { svcIp = IPAddress(); }
      discoverService(true);
    }
    return;
  }
  failStreak = 0;
  String body = http.getString();
  http.end();
  Serial.printf("[poll] %s\n", body.c_str());

  float ok = 0, v = -1, r = -1, stale = 0;
  bool hasOk  = jsonNumber(body, "ok", ok);
  bool hasPct = jsonNumber(body, "p7", v);      // finestra 7 giorni
  float v5 = -1, r5 = -1;
  bool hasSt  = jsonNumber(body, "stale", stale);

  usage.stale = hasSt && stale >= 0.5f;
  usage.ok    = hasOk && ok >= 0.5f && hasPct && v >= 0 && !usage.stale;
  // Un campo assente o nullo vale "non lo so" (-1), NON "tieni il valore di prima":
  // l'orario di reset si ricalcola da adesso a ogni ridisegno, quindi un valore vecchio
  // fa slittare la riga "reset" insieme all'orologio (visto: la finestra 5 ore inattiva
  // mostrava come reset l'ora corrente, e si spostava da sola).
  usage.pct7   = hasPct ? v : -1;
  usage.reset7 = jsonNumber(body, "r7", r)  ? (long)r  : -1;
  usage.pct5   = jsonNumber(body, "p",  v5) ? v5       : -1;
  usage.reset5 = jsonNumber(body, "r",  r5) ? (long)r5 : -1;
  if (!jsonString(body, "err", usage.err, sizeof(usage.err))) usage.err[0] = '\0';
  Serial.printf("[dato] 7g p=%.1f r=%ld | 5h p=%.1f r=%ld | err=\"%s\"\n",
                usage.pct7, usage.reset7, usage.pct5, usage.reset5, usage.err);

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

  loadCreds();
  view = creds.view;
#if defined(VIEW_FORCE)
  // Solo per il banco: forza la vista e la salva (es. -DVIEW_FORCE=0 per tornare a 7g).
  view = VIEW_FORCE;
  creds.view = view;
  EEPROM.put(0, creds);
  EEPROM.commit();
#endif
#if BUTTON_PIN >= 0
  pinMode(BUTTON_PIN, INPUT_PULLDOWN_16);   // l'unico pin con pull-down interno
#endif
  Serial.printf("[vista] %s, pulsante su GPIO%d\n", viewLabel(), (int)BUTTON_PIN);
  improvSerial.setDeviceInfo(ImprovTypes::ChipFamily::CF_ESP8266, "Claude Usage Ring",
                             FIRMWARE_VERSION, DEVICE_NAME);
  improvSerial.onImprovConnected(onImprovConnected);
  improvSerial.onImprovError(onImprovError);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  wifiUp();

  MDNS.begin(DEVICE_NAME);
  Serial.printf("[mdns] mi presento come %s.local\n", DEVICE_NAME);

  configTime(TZ_INFO, "pool.ntp.org", "time.cloudflare.com");
  struct tm tmv;
  timeSynced = getLocalTime(&tmv, 5000);
  Serial.printf("[ntp] orario %s\n", timeSynced ? "sincronizzato" : "non disponibile");

  discoverWithRetries(3);
  pollUsage();
  lastPoll = lastCountdown = millis();
}

void loop() {
  unsigned long now = millis();
  // Improv: il browser ha un tempo massimo di attesa, e la libreria legge UN byte per
  // chiamata: una sola chiamata per giro di loop consumava un comando in secondi (il
  // colloquio andava in timeout). Quindi si svuota tutto ciò che è arrivato sulla seriale.
  while (Serial.available() > 0) improvSerial.handleSerial();
  MDNS.update();          // il responder mDNS va servito, altrimenti le risposte scadono

  pollButton();

#if defined(VIEW_TOGGLE_TEST)
  // Prova in banco: cambia vista da sola ogni 10 s. Non entra nell'immagine pubblicata.
  static unsigned long lastTestToggle = 0;
  if (now - lastTestToggle >= 10000UL) {
    lastTestToggle = now;
    toggleView();
  }
#endif

  if (now - lastPoll >= (unsigned long)POLL_SECONDS * 1000UL) {
    lastPoll = now;
    pollUsage();
  }

  // countdown fra un poll e l'altro, senza rileggere il server
  if (lastState == 0 && viewReset() >= 0 && now - lastCountdown >= 20000UL) {
    lastCountdown = now;
    long elapsed = (long)((now - usage.millisAtFetch) / 1000UL);
    long left = viewReset() - elapsed;
    if (left < 0) left = 0;
    char cd[16];
    fmtCountdown(left, cd, sizeof(cd));
    textIfChanged(cd, Y_CDOWN, &FreeSans9pt7b, 1, C_TEXT, shownCountdown, sizeof(shownCountdown));
    char rz[24];
    fmtResetClock(left, rz, sizeof(rz));
    textIfChanged(rz, Y_RESET, &FreeSansBold9pt7b, 1, C_TEXT, shownReset, sizeof(shownReset));
  }

  delay(25);
}
