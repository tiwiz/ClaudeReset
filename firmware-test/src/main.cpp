/*
 * Pattern di prova per il display rotondo 240x240 su D1 mini (ESP8266).
 * ---------------------------------------------------------------
 * Scrive in seriale cosa fa e cicla colori pieni molto riconoscibili:
 *
 *   1) ROSSO      2) VERDE     3) BLU
 *   4) BIANCO     5) GRIGIO SCURO (sfondo dell'anello)
 *   6) anello arancione + "TEST"
 *
 * Serve a separare i due casi:
 *   - si vede qualcosa  -> il pannello e i fili funzionano, era il firmware
 *   - tutto nero        -> alimentazione / fili / modulo, oppure driver sbagliato
 *                          (prova un altro env: st7789, ili9341)
 *
 * Poi si torna al firmware vero: cd ../firmware && pio run -t upload
 */

#include <Arduino.h>
#include <TFT_eSPI.h>

static const int16_t CX = 120, CY = 120;

TFT_eSPI tft = TFT_eSPI();

struct Step { uint16_t color; const char *nome; };

static const Step STEPS[] = {
  { TFT_RED,     "rosso" },
  { TFT_GREEN,   "verde" },
  { TFT_BLUE,    "blu" },
  { TFT_WHITE,   "bianco" },
  { 0x18E3,      "grigio scuro (sfondo)" },
};

// anello arancione + scritta: riproduce quello che disegna il firmware vero
static void drawRingTest() {
  const uint16_t C_BG   = 0x0861;   // 0x0e0e11
  const uint16_t C_TRACK= 0x2B4A;   // 0x2b2b33
  const uint16_t C_ARC  = 0xD3AE;   // 0xd97757
  const uint16_t C_TEXT = 0xF7BE;   // 0xf5f5f5

  tft.fillScreen(C_BG);
  for (int grad = 0; grad < 360; grad++) {
    float rad = grad * 0.0174532925f;
    int16_t x = (int16_t)(CX + 103 * sinf(rad));
    int16_t y = (int16_t)(CY - 103 * cosf(rad));
    tft.fillCircle(x, y, 7, (grad < 216) ? C_ARC : C_TRACK);   // 60% di arco
  }
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(C_TEXT, C_BG);
  tft.setFreeFont(&FreeSansBold24pt7b);
  tft.drawString("60%", CX, 100, 0);
  tft.setFreeFont(&FreeSans9pt7b);
  tft.drawString("TEST", CX, 168, 0);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("[test] pattern display 240x240");
  Serial.printf("[test] driver=%s cs=12 dc=4 rst=5 mosi=13 sclk=14\n",
#if defined(GC9A01_DRIVER)
                "GC9A01"
#elif defined(ST7789_DRIVER)
                "ST7789"
#elif defined(ILI9341_DRIVER)
                "ILI9341"
#else
                "?"
#endif
  );

  tft.init();
  Serial.println("[test] tft.init() eseguito (nessun errore possibile: SPI in sola scrittura)");
  tft.setRotation(0);
  tft.fillScreen(TFT_BLACK);
  delay(500);
  Serial.println("[test] ciclo colori avviato: guarda lo schermo");
}

void loop() {
  for (unsigned i = 0; i < sizeof(STEPS) / sizeof(STEPS[0]); i++) {
    Serial.printf("[test] disco di %s\n", STEPS[i].nome);
    tft.fillScreen(STEPS[i].color);
    delay(2000);
  }
  Serial.println("[test] quadrante di prova (anello 60%)");
  drawRingTest();
  delay(4000);

  // giro di rotazioni: se il testo appare solo in alcune, e' un problema di orientamento
  for (int r = 0; r < 4; r++) {
    Serial.printf("[test] setRotation(%d) con 'TEST 1234'\n", r);
    tft.fillScreen(TFT_BLACK);
    tft.setRotation(r);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setFreeFont(&FreeSansBold24pt7b);
    tft.drawString("TEST", CX, 100, 0);
    tft.setFreeFont(&FreeSans9pt7b);
    tft.drawString("1234", CX, 150, 0);
    delay(2500);
  }
  tft.setRotation(0);
}
