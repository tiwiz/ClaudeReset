# Firmware — D1 mini (ESP8266) + GC9A01 240x240

Mostra l'utilizzo di Claude Code: anello arancione, percentuale al centro, reset sotto.
Il micro **non ha credenziali**: fa una `GET http://192.168.86.76:8790/claude` in LAN ogni
`POLL_SECONDS` secondi (vedi il poller nella cartella superiore).

## Configurazione (una volta sola)

```bash
cp include/config.h.example include/config.h
$EDITOR include/config.h     # SSID, password del wifi, host/porta del poller
chmod 600 include/config.h
```

`include/config.h` è nel `.gitignore`: le credenziali del wifi non finiscono nel repo, come per il
token di Claude Code nel `.env`. L'unico punto in cui un segreto tocca il progetto è il tuo file
locale.

## Compilare e flashare

```bash
~/.venvs/pio/bin/pio run                 # compila
~/.venvs/pio/bin/pio run -t upload       # flasha (scheda via USB)
~/.venvs/pio/bin/pio device monitor      # log seriale (115200)
```

Il toolchain PlatformIO è installato in `~/.venvs/pio` sulla build machine.
La prima compilazione scarica la piattaforma ESP8266 (~250 MB).

## Come è fatto

- **TFT_eSPI configurato da `platformio.ini`** (`-DUSER_SETUP_LOADED=1` e i pin come `build_flags`):
  niente `User_Setup.h` da editare a mano dentro la libreria, e i pin stanno accanto alla mappa in
  `docs/wiring.md`.
- **Nessun framebuffer**: 240x240 a 16 bit sono 115.200 byte e su ESP8266 ce ne sono ~40 KB liberi.
  L'anello si disegna con una banda di cerchi pieni (estremi tondi) e a ogni aggiornamento si
  ridisegna **solo il delta**: nuovo arco se la percentuale sale, cancellazione della parte vecchia
  se scende (reset della finestra), giro completo solo al cambio di soglia o di stato.
- **Il testo si aggiorna nel posto**: `setTextColor(fg, bg)` riempie lo sfondo dei glifi, quindi non
  serve cancellare a mano (tranne al cambio di stato, dove si rifà il quadrante).
- **Countdown vivo**: fra un poll e l'altro il countdown e l'orario di reset si aggiornano ogni 20 s
  scalando il valore letto, senza interrogare di nuovo il server. L'orario assoluto richiede l'NTP:
  se non è sincronizzato il display mostra solo il countdown.
- **Stati**: online (arco arancione) · sopra l'80% (arancio più caldo) · offline (anello grigio, `--`,
  motivo dell'errore al posto dell'orario). Un dato fermo non viene mai mostrato come fresco.

## Font

TFT_eSPI ha font a dimensione fissa. La percentuale usa `FreeSansBold24pt7b`: il font dichiara
`yAdvance = 56` px, quindi i numeri escono alti **~40 px**, non 64 come nel mockup. Con un corpo più
grande (`FreeSansBold18pt7b` a `setTextSize(2)`) i numeri arrivano a ~60 px ma `100%` sfora l'area
sicura (168 px). Per averli davvero a 64 px servono i "smooth font" `.vlw` generati con il tool di
TFT_eSPI (`SMOOTH_FONT=1`); il codice è già parametrico sul font (`textAt(...)`), è un cambio di due
righe.

## Da provare sul banco (non ancora verificato)

Questo firmware **compila** ed è pronto per il flash, ma non è mai stato eseguito su hardware: al
primo avvio controllare in quest'ordine — (1) il pannello si accende e il testo non è specchiato
(se lo è: `tft.setRotation(2)` o `invert_colors`), (2) l'anello riempie in senso orario da ore 12,
(3) la percentuale sta dentro il cerchio a `100%`, (4) il colore dell'arco cambia sopra l'80%.
