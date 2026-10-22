# improv (vendored)

`jnthas/Improv-WiFi-Library` v0.0.4, MIT, preso da
<https://github.com/jnthas/Improv-WiFi-Library> e incluso qui con **due correzioni**, entrambe
necessarie e verificate sul dispositivo. Se a monte le sistemano, si può togliere questa cartella e
rimettere `jnthas/Improv WiFi Library` in `lib_deps`.

## 1. L'include di FreeRTOS rompe la build ESP8266

La libreria dichiara `espressif8266` fra le piattaforme supportate, ma il suo
`ImprovWiFiLibrary.cpp` include `<freertos/FreeRTOS.h>` e `<freertos/task.h>` per qualunque build
ESP32 **o** ESP8266, e sull'ESP8266 quegli header non esistono:

    fatal error: freertos/FreeRTOS.h: No such file or directory

L'uso che ne fa è uno solo, `DELAY_MS(ms)` → `vTaskDelay(...)`. Qui l'include vale solo su ESP32 e
sull'ESP8266 il delay resta quello di Arduino.

## 2. Un frame perso ogni comando gestito

Misurato con due comandi in fila (due `GET_DEVICE_INFO`, oppure `GET_CURRENT_STATE` seguito da
`GET_DEVICE_INFO`): **una sola risposta**. Dopo aver consegnato un comando completo,
`parseImprovSerial` restituiva l'esito di `onCommandCallback` come "byte accettato", così
`handleSerial` accodava il byte di checksum e portava `_position` a `9 + data_len + 1`; il byte
successivo — la `I` del frame nuovo — finiva in un ramo che nessun `if` accettava e veniva
**scartato**. Un frame su due spariva: nel browser il flusso funzionava solo grazie ai
ritentativi, e il WiFi sembrava "a volte non accettato".

Il fix: a frame completo non si accoda più nulla e la posizione riparte da zero, così il byte
successivo viene letto come inizio del frame nuovo.

`ImprovWiFiBLE.*` non è stato copiato: il BLE è ESP32-only e tirerebbe dentro NimBLE per niente.
