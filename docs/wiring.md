# Layout e cablaggio — display tondo GC9A01 240×240 + D1 mini (ESP8266)

## Modulo display (ordine reale dei pin sul PCB, dall'alto verso il basso)

Serigrafia del modulo in uso: `RST · CS · DC · SDA · SCL · GND · VCC` — 7 pin, nessun pin di
retroilluminazione. Il `CS` del modulo va a massa, non su una porta: vedi la nota sui pin di strapping.

| # | Pad modulo | Pin D1 mini | GPIO | Funzione | Filo |
|---|---|---|---|---|---|
| 1 | RST | D1 | GPIO5 | reset del pannello | rosa |
| 2 | CS | D6 | GPIO12 | chip select | viola |
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
  sta su **D6 (GPIO12)**, mai su D8: il pull-up sul CS del modulo teneva GPIO15 alto e la scheda non
  partiva. (Variante equivalente: `CS` a GND con `TFT_CS=-1`.)
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
| Etichetta finestra (`7g`) | 20 px, ancorata al centro, y=62 |
| Percentuale della finestra **7 giorni** | FreeSansBold24pt7b, centro (120, 118) |
| Riga reset 7 giorni (`reset 12:40`) | FreeSansBold9pt7b, centro (120, 169) |
| Countdown (`2h 35m`) | FreeSans9pt7b, centro (120, 191) |
| Oltre l'80% | arco in `#e05a3a` |
| Offline | anello grigio, `--` al centro |
| Testo | bianco puro `#ffffff` su tutti i testi, la gerarchia la fa solo la dimensione |

Gli angoli del pannello sono fuori dal cerchio: non ci va nulla.

## Note sul firmware

- ESP8266: 240×240 a 16 bit = 115.200 byte, **non** entra nella RAM libera (~40 KB) → niente
  framebuffer: si disegnano traccia, arco e testo e si ridisegna **solo** quando cambia il valore.
- Libreria: TFT_eSPI configurato **da `build_flags`** (`-DUSER_SETUP_LOADED=1 -DGC9A01_DRIVER=1` + pin),
  così non si tocca nessun file della libreria.
- Polling di `GET /api/usage` ogni 30-60 s; anello grigio e `--` se `ok=0` o `stale=1`.

## Se lo schermo resta nero

Nell'ordine in cui conviene indagare:

1. **Separa hardware e software**: `cd firmware-test && pio run -e gc9a01 -t upload`. Quel progetto
   cicla colori pieni e rotazioni, non usa WiFi né `config.h`. Se lì si vede, il problema è nel
   firmware; se resta nero, è a monte.
2. **Altri controller**: `pio run -e st7789 -t upload` e `pio run -e ili9341 -t upload` (alcuni moduli
   rotondi venduti come GC9A01 montano in realtà controller diversi).
3. **I flag sono davvero applicati?** Con `USER_SETUP_LOADED` TFT_eSPI ignora il suo `User_Setup.h`;
   per verificarlo: `pio run --target compiledb` e controllare che il comando di compilazione di
   `TFT_eSPI.cpp` contenga `-DGC9A01_DRIVER=1` e i pin giusti.
4. **Alimentazione** — il modulo ha 7 pad e **nessun pin di retroilluminazione**: il LED è collegato
   internamente a VCC, quindi a VCC alimentato il pannello **deve** fare un alone fioco.
   *Nessun alone = problema di alimentazione*, e nessun driver o mappa pin lo risolverà.
5. **Giunto freddo su GND** — sintomo tipico, visto dal vivo in questo progetto: lo schermo si accende
   solo premendo il pad `GND` con un puntale del tester. Non è il puntale che alimenta (un voltmetro
   presenta ~10 MΩ, non manda corrente): è la **pressione** che ripristina il contatto. Si rifà il
   giunto sui pad `VCC` e `GND`, che sono gli unici due a portare corrente.
   Se il modulo è su basette a pin, il punto debole è la saldatura basetta↔pad, non il filo.

## Pulsante per cambiare finestra (opzionale)

Un contatto momentaneo fra **D0 (GPIO16)** e **3V3** fa passare il quadrante dalla finestra dei
7 giorni a quella delle 5 ore e viceversa. Entrambe le finestre arrivano nello stesso JSON, quindi
il cambio è istantaneo: nessuna richiesta in più.

| Dal | Al | Note |
|---|---|---|
| Un pin metallico del pulsante | **D0** (GPIO16) | lato sinistro della scheda |
| L'altro pin metallico | **3V3** | stesso lato, poche piazzole più sotto |
| Pin plastico (se è uno switch di tastiera) | — | serve solo a centrare il foro da 14x14 mm |

- **Nessuna resistenza**: GPIO16 è l'unico pin dell'ESP8266 con il **pull-down interno**, quindi a
  riposo legge basso e premuto legge alto. E se il pulsante non è collegato non succede nulla (un pin
  flottante cambierebbe vista da solo, e non è il caso).
- **Mai a 5 V**: il pin è a logica 3,3 V.
- **D3, D4 e D8 non si usano**: sono pin di strapping, e un pulsante premuto all'avvio impedisce alla
  scheda di partire (è lo stesso problema che ha reso necessario spostare il `CS` su D6).
- La scelta della finestra si ricorda in EEPROM, quindi sopravvive al riavvio.
- Il `3V3` deve alimentare **due** cose (il display e il pulsante): serve un giunto a tre vie — una
  basetta millefori con una pista, un morsetto a leva, o due fili pre-stagnati sullo stesso pad.
  Sull'altro lato, il filo del `3V3` del pulsante va tenuto di colore diverso da quello del display.
- Con un pulsante di tastiera (switch MX) il contatto è momentaneo normalmente aperto: si verifica in
  due secondi col tester in continuità fra i due pin metallici (aperto a riposo, chiuso premuto).

## Stati del quadrante (cosa scrive la riga sotto la percentuale)

| Stato | Riga del reset | Countdown |
|---|---|---|
| finestra attiva | `reset HH:MM` (in grassetto) | tempo che manca |
| finestra **inattiva** (vista 5h, nessuna sessione aperta) | `nessuna sessione` (in tondo) | `--` |
| dato non leggibile | motivo dell'errore, es. `non autenticato` | `--` |

Perché "nessuna sessione": l'API di Claude restituisce `resets_at: null` finché la finestra delle
5 ore non è aperta (parte con la prima richiesta), mentre quella settimanale ha sempre un'ancora.
Il trattino sembrava un dato mancante; a parole si capisce che è uno stato.

Vincolo di spazio: la riga sta dentro la corda del cerchio a `y=169`, che al bordo inferiore del
testo è ~154 px. In grassetto `nessuna sessione` misura 155 px (esce), in tondo 143 px (ci sta):
per questo i messaggi vanno in `FreeSans9pt7b` e l'orario in `FreeSansBold9pt7b`. Il firmware
misura e stampa questi numeri all'avvio (`[layout] ...`).
