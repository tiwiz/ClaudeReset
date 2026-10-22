# Claude Usage Ring

Oggetto da scrivania: un **display tondo GC9A01 240×240** pilotato da un **D1 mini (ESP8266)** che
mostra dal vivo l'utilizzo di Claude Code: anello di progresso arancione, percentuale al centro,
orario del prossimo reset sotto.

```
┌─────────────────────────┐        ┌──────────────────────────┐        ┌───────────────────┐
│  Claude Code (build .76) │        │  poller (questo repo)    │        │  D1 mini + GC9A01 │
│  ~/.claude/…credentials  │───────▶│  GET api.anthropic.com   │───────▶│  GET :8790/claude │
│  token OAuth, mai esposto│        │  /api/oauth/usage 60 s   │        │  disegna 30-60 s  │
└─────────────────────────┘        │  HTTP JSON sulla LAN     │        └───────────────────┘
                                   └──────────────────────────┘
```

## Cosa fa il poller

Legge il token OAuth dal file di credenziali di Claude Code (lo stesso file che usa `claude`),
interroga l'endpoint di utilizzo che sta dietro `claude /usage` e ripubblica il risultato come JSON
compatto su una porta della LAN. Il micro non ha **nessun** segreto: fa una GET HTTP in chiaro
sulla LAN e disegna.

| Endpoint | Cosa restituisce |
|---|---|
| `GET /claude` | JSON compatto per il micro (chiavi corte, sotto) |
| `GET /` o `/usage` | riepilogo leggibile per un umano |
| `GET /health` | 200 se il dato è fresco, 503 se fermo (`age`, `error`) |

```json
{"ok":1,"p":23.0,"r":5220,"p7":61.0,"r7":30600,"age":12,"stale":0,"err":""}
```

| Campo | Significato |
|---|---|
| `ok` | 1 se c'è un dato utilizzabile |
| `p` | utilizzo della finestra a **5 ore** (percentuale) → è il valore dell'anello |
| `r` | secondi al **prossimo reset** della finestra 5 ore |
| `p7`, `r7` | come sopra per la finestra a **7 giorni** (archetto secondario) |
| `age` | secondi da quando il dato è stato letto |
| `stale` | 1 se il dato è più vecchio di `STALE_SECONDS` |
| `err` | ultimo errore, in chiaro (es. `token scaduto`) |

## Installazione (sulla build machine, utente `rob`)

```bash
mkdir -p ~/projects && cd ~/projects
git clone <questo repo> claude-usage-ring   # oppure: è già qui
cd claude-usage-ring
cp .env.example .env                        # poi adatta i valori
mkdir -p ~/.config/systemd/user
cp systemd/claude-usage.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-usage.service
curl -s localhost:8790/claude | python3 -m json.tool
```

Per una prova senza systemd:

```bash
python3 poller/claude_usage.py
```

Serve `linger` attivo (`loginctl enable-linger rob`) perché l'unit utente parta al boot.
Se c'è `ufw`: `sudo ufw allow from 192.168.86.0/24 to any port 8790 proto tcp`.

## Segreti

- Il token **non è nel repo** e non lo sarà: viene letto a runtime dal file di credenziali di
  Claude Code, che resta dov'è.
- `.env` è configurazione (percorsi, porta, intervalli) ed è nel `.gitignore`; il repo contiene
  solo `.env.example`.
- L'unica variabile che potrebbe contenere un token è `CLAUDE_OAUTH_TOKEN`, pensata per le prove:
  vive solo in `.env` locale.
- Il poller non logga mai il token, né lo restituisce via HTTP.

## Cablaggio

Mappa completa, ordine reale dei pad del modulo e geometria del quadrante: `docs/wiring.md`.

## Firmware

`firmware/` — sketch Arduino per D1 mini con TFT_eSPI (pin configurati da `platformio.ini`, niente
`User_Setup.h` da editare). Anello + arco disegnati come banda di cerchi pieni, ridisegno solo del
delta perché su ESP8266 il framebuffer non entra. Dettagli, comandi `pio` e cosa controllare al
primo avvio: `firmware/README.md`.

```bash
cd firmware
cp include/config.h.example include/config.h   # wifi + host del poller, poi chmod 600
~/.venvs/pio/bin/pio run                       # compila
~/.venvs/pio/bin/pio run -t upload             # flasha
```

## Stato

- [x] poller + unit systemd, verificato sulla build machine
- [x] firmware ESP8266: compila (RAM 37%, flash 36%) — da provare sul banco
- [ ] archetto secondario per la finestra a 7 giorni
- [ ] custodia


## Note

- Il token OAuth scade (Claude Code lo rinnova quando lo usi): se scade, il poller marca
  `err="token scaduto"` e il display va in stato offline invece di mostrare un numero fermo.
  Un valore vecchio mostrato come fresco è peggio di un display spento.
