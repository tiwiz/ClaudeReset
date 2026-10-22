# Layout e cablaggio — display tondo GC9A01 240×240 + D1 mini (ESP8266)

## Modulo display (ordine reale dei pin sul PCB, dall'alto verso il basso)

Serigrafia del modulo in uso: `RST · CS · DC · SDA · SCL · GND · VCC` — 7 pin, nessun pin di
retroilluminazione. Il `CS` del modulo va a massa, non su una porta: vedi la nota sui pin di strapping.

| # | Pad modulo | Pin D1 mini | GPIO | Funzione | Filo |
|---|---|---|---|---|---|
| 1 | RST | D1 | GPIO5 | reset del pannello | rosa |
| 2 | CS | **GND** | — | chip select, fisso a massa (bus con un solo dispositivo) | viola |
| 3 | DC | D2 | GPIO4 | data/command | giallo |
| 4 | SDA | D7 | GPIO13 | MOSI (hardware SPI) | verde |
| 5 | SCL | D5 | GPIO14 | clock SPI (hardware SCK) | ciano |
| 6 | GND | GND | — | massa comune | grigio |
| 7 | VCC | 3V3 | — | alimentazione 3,3 V | rosso |

Da non sbagliare:

- `VCC` a **3V3**, mai a 5 V / `VBUS`: la logica del GC9A01 è a 3,3 V.
- `GND` in comune obbligatorio.
- **D3 (GPIO0), D4 (GPIO2) e D8 (GPIO15)** sono pin di strapping: all'avvio devono stare al livello
  giusto, altrimenti l'ESP8266 non parte e non si fa nemmeno flashare. Per questo il `CS` del display
  **non sta su D8**: va a **GND** (il bus ha un solo dispositivo) e nel firmware si mette `TFT_CS=-1`.
  Alternativa se si vuole CS pilotato: `D6` (GPIO12), mai GPIO15.
- Se il modulo avesse un ottavo pin di retroilluminazione (`BLK`/`LED`), va a 3V3.
- L'ordine dei pad sul foglio **non** è l'ordine sulla scheda: conta il nome serigrafato.
- Lasciare 8-10 cm di filo per ogni collegamento, per richiudere in custodia.

## Geometria del quadrante (spazio 240×240, 1 px = 1 px del pannello)

| Elemento | Valore |
|---|---|
| Traccia anello | `circle r=103`, spessore 14 px, colore `#2b2b33` |
| Arco di utilizzo | da ore 12 (−90°), senso orario, angolo = 360° × pct, colore `#d97757`, estremità arrotondate |
| Bordo pannello | r 110 (Ø 220) |
| Area sicura per il testo | r 84 |
| Etichetta finestra (`5h`) | 20 px, ancorata al centro, y=62 |
| Percentuale | 64 px bold, centro (120, 142) |
| Riga reset (`reset 12:40`) | 22 px, centro (120, 172) |
| Countdown (`2h 35m`) | 16 px, centro (120, 194) |
| Oltre l'80% | arco in `#e05a3a` |
| Offline | anello grigio, `--` al centro |

Gli angoli del pannello sono fuori dal cerchio: non ci va nulla.

## Note sul firmware

- ESP8266: 240×240 a 16 bit = 115.200 byte, **non** entra nella RAM libera (~40 KB) → niente
  framebuffer: si disegnano traccia, arco e testo e si ridisegna **solo** quando cambia il valore.
- Libreria: TFT_eSPI (`User_Setup` con driver GC9A01, pin come in tabella) oppure LovyanGFX.
- Polling di `GET /claude` ogni 30-60 s; anello grigio e `--` se `ok=0` o `stale=1`.
