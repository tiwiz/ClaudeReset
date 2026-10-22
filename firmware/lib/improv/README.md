# improv (vendored)

`jnthas/Improv-WiFi-Library` v0.0.4, MIT, preso da
<https://github.com/jnthas/Improv-WiFi-Library> e incluso qui per una ragione sola.

La libreria dichiara `espressif8266` fra le piattaforme supportate, ma il suo
`ImprovWiFiLibrary.cpp` include `<freertos/FreeRTOS.h>` e `<freertos/task.h>` per
qualunque build ESP32 **o** ESP8266, e sull'ESP8266 quegli header non esistono:

    fatal error: freertos/FreeRTOS.h: No such file or directory

L'uso che ne fa è uno solo, `DELAY_MS(ms)` → `vTaskDelay(...)`. La correzione qui applicata
limita l'include all'ESP32 e sull'ESP8266 usa il `delay()` di Arduino; il comportamento del
protocollo è identico. La libreria è inclusa invece di essere una dipendenza di
`platformio.ini` così un clone pulito compila senza dipendere da una release rotta, e resta
riproducibile.

`ImprovWiFiBLE.*` non è stato copiato: il BLE è ESP32-only e tirerebbe dentro NimBLE per
niente su questa scheda.

Se in futuro la libreria a monte sistema l'include, si può tornare alla dipendenza normale
rimuovendo questa cartella e rimettendo `jnthas/Improv WiFi Library` in `lib_deps`.
