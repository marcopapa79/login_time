# login_time — Design Brief e razionale delle scelte

Documento pensato per due usi:

1. **Da dare in pasto a Claude (design)** per ridisegnare la UI senza rompere la logica esistente → sezioni 1–5.
2. **Capire il perché** di alcune soluzioni tecniche adottate nel codice → sezioni 6–8.

---

## 1. Cos'è l'app (contesto per il designer)

App desktop personale (Python + Tkinter, Windows) per **registrare localmente le ore lavorate** su ticket del supporto Quixant e **sincronizzarle** poi sul portale Quixant Hub (`https://support.quixant.com`) via API, senza passare dalla web UI.

Utente unico: un tecnico di supporto che a fine giornata/mese deve:

- loggare ore su ticket (`QUIX-xxx`, `SFTC-xx`, …);
- loggare ferie/malattia/permessi ("Extra Off");
- verificare che il totale del mese torni con le ore lavorative attese (giorni feriali italiani × 8h);
- inviare tutto al portale (sync API) e controllare il Monthly Report.

**Obiettivo principale della UI:** a colpo d'occhio sapere *quante ore mancano* e *cosa è ancora da sincronizzare* nel mese selezionato.

---

## 2. Inventario schermate attuali

| # | Schermata | Tipo | Dove nel codice |
|---|-----------|------|-----------------|
| 1 | Login | finestra principale | [ui.py](../src/login_time/ui.py#L64) `_build_login_ui` |
| 2 | Dashboard | finestra principale | [ui.py](../src/login_time/ui.py#L165) `_show_dashboard` |
| 3 | Lista worklog (card per ticket) | dentro dashboard, scrollabile | [ui.py](../src/login_time/ui.py#L993) `_render_worklogs` |
| 4 | Log working time / Extra Off / Import | modale | [ui.py](../src/login_time/ui.py#L567) `_open_worklog_window` |
| 5 | Open Ticket | modale | [ui.py](../src/login_time/ui.py#L482) `_open_ticket_window` |
| 6 | API Ticket Update (tester API) | modale grande | [ui.py](../src/login_time/ui.py#L1221) `_open_api_update_window` |
| 7 | Edit Extra Hours Payload (JSON) | modale | [ui.py](../src/login_time/ui.py#L1980) `_edit_extra_hours_payload` |
| 8 | Edit description (per ticket) | modale | [ui.py](../src/login_time/ui.py#L2466) |
| 9 | Edit log (singola riga) | modale | [ui.py](../src/login_time/ui.py#L2508) |

### 2.1 Login
- Card centrata: titolo `QUIXANT` (arancio), sottotitolo "Log in", Username, Password, bottoni **LOG IN** (primario) e **Save as default** (secondario).
- Il login è **solo locale** (confronto con credenziali salvate); il login API vero avviene dopo, on-demand.

### 2.2 Dashboard
Dall'alto verso il basso:
1. **Barra riepilogo** (una riga di testo):
   `Mese  Total: Xh (OK|CHECK)  Local: Xh  Extra Off: Xh  API synced: Xh  Pending: Xh  Missing: Xh`
2. **Azioni globali**: `Monthly Report` (apre browser), `Open Ticket`, `API Sync Month`, `Import QxSupport Month`.
   A destra: campo `Search` (oggi non funzionante) e avatar `MP` con menu profilo (solo *Logout* è attivo).
3. Titolo "Welcome {Nome}" + "Dashboard ready".
4. **Pannello worklog**:
   - azioni di inserimento: `+ Log new working time`, `+ Add Extra Off (Ferie)`, `+ Add QxSupport (synced)`, `+ Import existing ticket`;
   - switch mese: `Current Month`, `Previous Month`, `Two Months Ago` + etichetta vista attiva;
   - lista di **card raggruppate per ticket**.

### 2.3 Card ticket (elemento centrale)
- Header: codice ticket (bold), descrizione, stato `API synced: N | Pending: M` (verde se 0 pending, giallo altrimenti).
- Azioni ticket: `Open ticket` (non per OFF), `Copy description`, `Edit description`, `API sync ticket` / `API sync off`.
- Righe: `Working time | Month | Work log` + azioni per riga: `Copy work log`, `Copy working time`, `Remove`, badge stato (`Pending API` / `Synced 2026-10-23 10:12` / `Off pending API` / `Off synced …`), `API update log` (solo se pending), `Edit log`.

### 2.4 Modale "Log working time"
- Campo Ticket (combobox con ticket già usati `CODICE | titolo`).
- Radio **Type**: `Work` · `Extra Off / Ferie` · `QxSupport (already synced)` · `Ticket (already synced)`.
- `Off type` (visibile solo per Off): Annual Leave, Sick Leave, Permit, Other.
- Working time (formati: `1h`, `2.5h`, `1d`, `1d 4h`, `3`), Description, Comment (obbligatorio).
- Il form si **auto-adatta** al tipo: per Off blocca il ticket su `OFF` e propone `8h`; per QxSupport blocca su `QXSUPPORT`; per Ticket synced propone `SFTC-`.

---

## 3. Design tokens attuali

| Token | Valore | Uso |
|-------|--------|-----|
| bg-app | `#1f1f22` | sfondo finestra / dashboard |
| bg-surface | `#2b2b30` | card login, modali |
| bg-panel | `#14161b` | pannello worklog |
| bg-card | `#171a20` | card ticket |
| border | `#2c2f36` | bordi pannelli/card |
| btn-secondary | `#3a3a40` (hover `#4a4a50`) | quasi tutti i bottoni |
| accent / primary | `#ff6a00` (hover `#e65f00`) | brand Quixant, CTA, divider |
| text-primary | `#f4f4f6` | testo |
| text-muted | `#bcbcc7` | descrizioni, label secondarie |
| status-ok | `#8fd18a` | synced |
| status-warn | `#d8c27a` | pending |
| font | Segoe UI (UI), Consolas (JSON) | |

Tema: **dark**, accent arancio Quixant.

---

## 4. Problemi UX noti (input per il redesign)

- **Troppi bottoni grigi uguali** per riga (fino a 6): nessuna gerarchia visiva. Candidati a icone o menu "⋯".
- Barra riepilogo è **una riga di testo**: andrebbe resa come KPI/cards (Target, Logged, Missing, Pending) con progress bar.
- 4 bottoni "+ …" separati per l'inserimento: meglio un unico **"+ New entry"** con scelta del tipo dentro il modale (che già esiste).
- Switch mese limitato a 3 valori fissi: meglio un **month picker ◀ Ottobre 2026 ▶**.
- `Search` e voci del menu profilo sono **placeholder non funzionanti**.
- Feedback tramite `messagebox` modali anche per successi banali → meglio **toast/snackbar**.
- La lista mostra **al massimo 20 righe** per mese (vedi §7) senza dirlo all'utente.
- Il tester API (schermata 6) è uno strumento da sviluppatore: va separato/nascosto (es. sezione "Advanced / Debug").
- Testi misti italiano/inglese.

---

## 5. Prompt pronto per Claude (design)

> Copia/incolla quanto segue, allegando questo file.

```
Sei un product designer. Ridisegna la UI di un'app desktop (Python/Tkinter, Windows, tema dark,
accent arancio #ff6a00) per il log delle ore su ticket e la loro sincronizzazione con un portale
aziendale. Usa il documento allegato come fonte di verità su schermate, flussi e vincoli.

Vincoli:
- Deve restare implementabile in Tkinter/ttk (niente effetti web-only: blur, ombre complesse,
  animazioni CSS). Layout a frame/grid, font Segoe UI, icone semplici (unicode o PNG).
- Non cambiare il modello dati né i flussi API (sezioni 6-7): cambia solo presentazione e interazione.
- Utente unico, uso quotidiano, schermo 1366x768 minimo, finestra massimizzata.

Obiettivi:
1. Dashboard con KPI del mese (Target, Logged, Extra Off, Synced, Pending, Missing) + stato OK/CHECK.
2. Month picker al posto dei 3 bottoni fissi.
3. Card ticket più pulite: azioni primarie visibili (Sync, Edit), secondarie in menu overflow.
4. Un solo entry point "New entry" con tipo selezionabile nel modale.
5. Feedback non bloccante (toast) per successi; modale solo per errori/conferme distruttive.
6. Spostare il tester API in un'area "Advanced".

Output richiesto:
- Wireframe/mockup di: Login, Dashboard, Card ticket (stato pending e synced), Modale New entry
  (varianti Work / Extra Off), Toast, Month picker.
- Tabella design tokens aggiornata (colori, spaziature, font size).
- Per ogni schermata: elenco componenti Tkinter suggeriti (Frame, ttk.Treeview, Canvas, ecc.).
```

---

## 6. Modello dati

### File locali (root del progetto)
| File | Contenuto |
|------|-----------|
| `credentials.json` | username/password salvati con "Save as default" |
| `worklogs.json` | lista di righe worklog (più recenti in testa) |
| `ticket_uuid_cache.json` | mappa `CODICE-TICKET → UUID` del portale |

### Riga worklog
```json
{
  "working_time": "1d 4h",
  "month": "October 2026",
  "work_log": "...", "comment": "...",
  "ticket": "QUIX-707",
  "description": "titolo ticket",
  "entry_type": "work | off | qxsupport_synced | ticket_synced",
  "off_type": "Annual Leave",
  "log_date": "2026-10-23",
  "api_synced": "true | \"\"",
  "api_synced_at": "2026-10-23T10:12:00+02:00",
  "api_ticket_uuid": "XXXXXXXX-....",
  "api_month_displacement": "0"
}
```

---

## 7. Il perché delle scelte tecniche

### Tkinter + stdlib (`urllib`) senza dipendenze
Gira su qualsiasi Python Windows senza `pip install`, avviabile da [login_time.bat](../login_time.bat). Costo: UI meno moderna e codice UI verboso (ogni bottone ha 10 righe di stile).

### Tutti i valori salvati come stringhe (`"true"` invece di `true`)
[config.py](../src/login_time/config.py#L65) normalizza ogni campo con `str(...)`. Scelta di robustezza: file JSON vecchi o editati a mano non rompono il caricamento; campi mancanti ricevono un default.

### `month` salvato come etichetta (`"October 2026"`) + `MonthDisplacement`
L'API `/api/working_hours/form` non vuole una data ma uno **spostamento relativo** al mese corrente (`0` = questo mese, `-1` = scorso). Il mese assoluto è salvato localmente e il displacement è **ricalcolato al momento del sync** ([ui.py](../src/login_time/ui.py#L1855)), così una riga di settembre sincronizzata a ottobre invia correttamente `-1`.

### Cache `ticket → UUID`
L'API vuole l'UUID interno del ticket, non `QUIX-707`. Risolverlo richiede di scaricare intere liste ticket (`/api/tickets/list2` e `/list`, open → closed → archived), che possono essere **molto pesanti**. Per questo:
- risultato salvato in `ticket_uuid_cache.json` e riusato per sempre;
- all'avvio la cache è popolata anche dagli UUID già presenti nei worklog ([ui.py](../src/login_time/ui.py#L1597));
- le varianti `archived=True` sono state aggiunte perché i ticket archiviati non venivano mai trovati;
- timeout portato a **45s** e errori di timeout tradotti in un messaggio leggibile ([api_client.py](../src/login_time/api_client.py#L112)).

Ecco perché alcuni ticket "funzionano subito" (in cache) e altri andavano in timeout (non in cache).

### Login API "a tentativi" ed estrazione token ricorsiva
[api_client.py](../src/login_time/api_client.py#L25) prova JSON e poi form-encoded; `_extract_token` cerca il token in vari nomi di campo e anche annidato. L'API non è documentata: la soluzione tollera variazioni del formato di risposta.

### Extra Off: GUID chiesto al server prima dell'insert
Dettagli in [extra-off-api.md](extra-off-api.md). In breve: se si manda `uuid` vuoto l'API risponde OK ma la voce **non compare nel Monthly Report**. Quindi: `GET /api/tickets/newguid` → `POST /api/extrahours/add` con date `dd/mm/yyyy` e `id_clockify_task` preso dalla mappa in [config.py](../src/login_time/config.py#L15) (alias italiani `ferie`, `malattia` supportati).

### "This entry is locked" trattato come successo
Significa che la voce esiste già per quella data/tipo. Per evitare duplicati e retry infiniti la riga viene marcata come sincronizzata ([ui.py](../src/login_time/ui.py#L2053)).

### Tipi `qxsupport_synced` / `ticket_synced`
Servono a importare ore **già presenti sul portale** (inserite a mano dal web) così che i totali locali tornino, senza re-inviarle. Nascono già con `api_synced = "true"`.

### Import QxSupport con endpoint "candidati"
[ui.py](../src/login_time/ui.py#L2210) prova più endpoint e scansiona ricorsivamente la risposta cercando progetti "QxSupport". Se trova righe dettagliate le importa una a una, altrimenti crea una riga aggregata. Deduplica con una firma `mese|ticket|ore|commento`. Approccio esplorativo perché il formato reale non è noto.

### Ore attese del mese
Giorni lun–ven esclusi i festivi italiani (Pasqua calcolata con l'algoritmo gregoriano anonimo) × 8h. `OK` solo se il totale locale coincide esattamente. Non considera patrono locale né part-time.

### Modifica di una riga = torna "pending"
[ui.py](../src/login_time/ui.py#L2548) azzera lo stato sync dopo un edit, così la modifica può essere reinviata.

---

## 8. Limiti e rischi da conoscere

- **Credenziali in chiaro** in `credentials.json` e default hardcoded in [config.py](../src/login_time/config.py#L7) (e nel README). Da spostare in Windows Credential Manager (`keyring`) ed eliminare dal repository.
- **Re-sync dopo edit può duplicare** le ore sul portale: l'app non cancella la voce remota precedente.
- `_group_worklogs_by_ticket` mostra solo le **prime 20 righe** del mese ([ui.py](../src/login_time/ui.py#L2437)); i totali invece le contano tutte.
- Il template "Add extra off" nel tester API usa ancora i nomi campo vecchi (`Type`, `IdClockifyTask`, `Hours`, `Description`), mentre il sync dalla dashboard usa quelli verificati (`id_clockify_task`, `hours`, `description`).
- Tutte le chiamate API sono **sincrone sul thread UI**: durante un sync la finestra si blocca (fino a 45s per richiesta).
- `ui.py` è un unico file da ~2600 righe che mescola UI, logica di business e chiamate API: un redesign è l'occasione per separare almeno *logica worklog/sync* da *widget*.
