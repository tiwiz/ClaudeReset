// Valori di default, questi sì committati: il firmware deve compilare e girare anche
// senza config.h, che è locale e gitignorato. Se config.h c'è, i suoi valori vincono.
//
// Nota: niente righe che iniziano con '#' se non sono direttive.

#pragma once

// --- il servizio (si scopre via mDNS, vedi main.cpp) ---
#ifndef MDNS_SERVICE
#define MDNS_SERVICE "claudereset"
#endif
#ifndef SERVICE_PATH
#define SERVICE_PATH "/api/usage"
#endif
// solo ripiego, se nessuno risponde all'annuncio
#ifndef SERVICE_PORT
#define SERVICE_PORT 8790
#endif
#ifndef FALLBACK_HOST
#define FALLBACK_HOST "192.168.86.42"
#endif

// --- nome con cui il display si presenta in rete ---
#ifndef DEVICE_NAME
#define DEVICE_NAME "claude-ring"
#endif

// --- cadenza di lettura e fuso orario ---
#ifndef POLL_SECONDS
#define POLL_SECONDS 30
#endif
#ifndef TZ_INFO
#define TZ_INFO "CET-1CEST,M3.5.0,M10.5.0/3"
#endif

#ifndef FIRMWARE_VERSION
#define FIRMWARE_VERSION "1.0.1"
#endif

// --- rete ---
// La rete non ha default: o arriva dal browser via Improv (immagine pubblica del
// flasher, che così non contiene nessun segreto) o da config.h (build locale).
// Restano come ripiego quando ci sono: vedi loadCreds() in main.cpp.
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif
