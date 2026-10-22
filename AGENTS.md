# AGENTS.md — Claude Usage Ring

Handoff per i CLI (claude, amp, agy, opencode). Tenerlo aggiornato: è il punto di ingresso del progetto.

## Cosa è

Ponte dati + display fisico: l'utilizzo di Claude Code (finestra 5 ore e 7 giorni) è letto
dall'endpoint che usa `claude /usage` da un poller Python, risposto come JSON sulla LAN, e disegnato
su un pannello tondo GC9A01 240×240 pilotato da un D1 mini (ESP8266).

Componenti:

| Pezzo | Dove | Stato |
|---|---|---|
| Poller `poller/claude_usage.py` (stdlib, nessuna dipendenza) | unit utente `claude-usage.service` sulla build machine | fatto e verificato |
| Firmware ESP8266 | `firmware/` (da fare) | da fare |
| Documentazione cablaggio/geometria | `docs/wiring.md` | fatto |

## Regole del progetto

- **Nessun segreto nel repo, mai.** Il token di Claude Code si legge a runtime da
  `CLAUDE_CREDENTIALS` (`.env`, gitignorato). Non stampare token nei log, non restituirli via HTTP,
  non metterli nel firmware. Un micro è leggibile da chi lo ha in mano.
- **Commenti e documenti in italiano**, codici identificativi e nomi dei campi JSON in inglese.
- Il contratto dell'endpoint `/claude` è stabile: `ok, p, r, p7, r7, age, stale, err`. Se cambia,
  aggiornare `README.md` e il firmware insieme.
- Il quadrante si progetta **nello spazio pixel del pannello** (240×240), non in coordinate di
  comodo: le quote in `docs/wiring.md` si copiano 1:1 nel firmware.
- ESP8266 = nessun framebuffer (115 KB non entrano in ~40 KB di RAM): si ridisegna solo ciò che
  cambia. Non promettere sprite pieni su questa scheda.

## Comandi utili

```bash
systemctl --user status claude-usage.service
journalctl --user -u claude-usage.service -n 30 --no-pager
curl -s localhost:8790/claude | python3 -m json.tool
curl -s localhost:8790/health
python3 poller/claude_usage.py        # esecuzione manuale in foreground
```

## Stato e prossimo passo

Il poller gira e risponde. Prossimo passo: firmware ESP8266 con TFT_eSPI (driver GC9A01, pin in
`docs/wiring.md`), disegno diretto di traccia + arco + testo, aggiornamento solo al cambio di valore,
stato offline quando `ok=0` o `stale=1`.
