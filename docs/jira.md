# login_time – Pagina Jira

La pagina **Jira** (selettore "Ore · Hub | Jira" in alto, oppure Ctrl+1 / Ctrl+2) mostra le
issue di Jira Cloud (`https://quixantplc.atlassian.net`) senza aprire il browser.
Aggiornato al 05/11/2026.

---

## 1. Due modi per collegarsi

| | Login Atlassian · Duo (consigliato) | API token |
|---|---|---|
| Come entri | Nel browser: Microsoft → password → **Duo** → "Accetta" | Crei un token una volta su id.atlassian.com e lo incolli |
| Duo | Al collegamento, e di nuovo se non usi Jira dall'app per 90 giorni o revochi l'accesso | Solo quando crei il token |
| Cosa salva l'app | Secret dell'integrazione + token di rinnovo (Gestore credenziali) | Il token (Gestore credenziali) |
| Revoca | id.atlassian.com → App collegate, oppure menu ⋯ → "Scollega" | Pagina dei token → Revoke |

In nessuno dei due casi l'app vede o salva la password Microsoft: il login aziendale resta nel browser.

## 2. Login Atlassian con Duo (OAuth 2.0)

### 2.1 Una volta sola: l'integrazione nella developer console

1. Apri `https://developer.atlassian.com/console/myapps/` (pulsante **"Apri la developer
   console ↗"** nella pagina Jira dell'app).
2. **Create → OAuth 2.0 integration**, nome a piacere (es. `check_ticket`),
   **Access type: Resource-level**: l'accesso vale solo per il sito scelto al login.
3. **Permissions → Jira API → Configure**: `read:jira-work`, `write:jira-work`, `read:jira-user`.
4. **Authorization → OAuth 2.0 (3LO) → Configure**: Callback URL `http://localhost:53682/callback`.
5. **Settings**: copia **Client ID** e **Secret** e incollali nell'app (non in chat né in email).

L'integrazione resta privata: la usi solo tu.

### 2.2 Il login

1. Pagina Jira → scheda **"Login Atlassian · Duo"** → controlla sito, Client ID e Secret.
2. **"Accedi con Atlassian ↗"**: si apre il browser.
3. Login aziendale (Microsoft → password → Duo), poi nella pagina Atlassian scegli
   `quixantplc.atlassian.net` e premi **"Accetta"**. Atlassian può avvisare che l'app non è
   verificata: è la tua integrazione.
4. Il browser mostra "Jira collegato a login_time": chiudi la scheda e torna all'app.

Dopo il primo login il vecchio API token viene tolto da questo PC: revocalo anche dalla
pagina dei token Atlassian.

Agli avvii successivi l'app usa il token di rinnovo e non chiede niente. Il login con Duo
torna se:
- non usi Jira dall'app per **90 giorni**;
- revochi l'accesso (id.atlassian.com → App collegate) o premi "Scollega";
- gli admin Atlassian bloccano l'integrazione.

Menu ⋯ della pagina Jira: "Rifai il login (Microsoft + Duo)…", "App collegate al mio
account Atlassian ↗", "Usa un API token…", "Scollega Jira da questo PC" (Client ID e Secret
restano: il login successivo è un clic).

## 3. In alternativa: API token

1. Nella pagina Jira scegli la scheda **"API token"** e premi **"Apri la pagina dei token ↗"**. Si apre
   `https://id.atlassian.com/manage-profile/security/api-tokens`: fai il login come sempre
   (Microsoft → password → Duo).
2. Scegli **"Create API token with scopes"** (consigliato):
   - nome: `login_time`;
   - scadenza: quella che preferisci (massimo 365 giorni);
   - app: **Jira**;
   - scope: `read:jira-work`, `write:jira-work`, `read:jira-user`.

   Va bene anche **"Create API token"** (classico, senza scope).
3. Copia il token (Atlassian lo mostra una volta sola).
4. Torna all'app e controlla i campi:
   - **Sito**: `https://quixantplc.atlassian.net`;
   - **Email**: quella del tuo account Atlassian, cioè l'email aziendale;
   - **Token**: incollalo.

   Poi premi **Collega**.

L'app verifica il token con `GET /rest/api/3/myself` e solo se funziona lo salva.

## 4. Cosa si può fare

| Funzione | Dove | API Jira |
|----------|------|----------|
| Elenco issue: Da fare / Completate (30 gg) / Segnalate da me / Che seguo | Pagina Jira | `POST /rest/api/3/search/jql` |
| Filtro veloce per chiave o titolo | Campo "Filtra" | (locale) |
| Dettagli, descrizione, commenti | Clic su una issue | `GET /issue/{key}`, `GET /issue/{key}/comment` |
| Figli di un'epica (o sotto-task di una issue), con % completato; clic per aprirli | Finestra issue → "Figli" | `POST /search/jql` con `parent = "KEY" ORDER BY rank ASC` |
| Aprire l'issue padre (es. l'epica) | Finestra issue → "Padre" | `GET /issue/{key}` |
| Registrare ore (worklog) con data, ora di inizio e descrizione | Finestra issue → "Registra ore" | `POST /issue/{key}/worklog` |
| Aggiungere un commento | Finestra issue → "Commento" | `POST /issue/{key}/comment` |
| Cambiare stato | Finestra issue → "Cambia stato" | `GET`/`POST /issue/{key}/transitions` |
| Aprire la issue nel browser | Icona ↗ | `/browse/{key}` |

I filtri usano queste JQL:
- **Da fare**: `assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC`
- **Completate (30 gg)**: `assignee = currentUser() AND statusCategory = Done AND updated >= -30d`
- **Segnalate da me**: `reporter = currentUser() AND statusCategory != Done`
- **Che seguo**: `watcher = currentUser() AND statusCategory != Done`

Le ore registrate su Jira **non** vengono inviate al portale Quixant Hub: sono due sistemi
separati. Per il portale si usa la pagina "Ore · Hub".

## 5. Dettagli tecnici

Codice:
- `src/login_time/jira_client.py`: client REST v3, solo libreria standard Python;
- `src/login_time/jira_oauth.py`: login OAuth 2.0 (3LO) nel browser, rinnovo del token;
- `src/login_time/jira_page.py`: pagina e finestra della issue;
- `src/login_time/config.py`: `load_jira_settings`, `save_jira_settings`, `forget_jira_token`,
  `load_jira_oauth`, `save_jira_oauth`, `save_jira_oauth_refresh`, `forget_jira_oauth`.

Login Atlassian (OAuth 2.0 3LO):
- l'app apre `https://auth.atlassian.com/authorize` con gli scope sopra più `offline_access`
  (serve per il token di rinnovo) e un `state` casuale;
- un piccolo server in ascolto **solo su 127.0.0.1:53682** riceve il ritorno del browser e
  accetta solo la risposta con lo stesso `state`; si chiude subito dopo (o dopo 5 minuti,
  o con "Annulla login");
- il codice viene scambiato su `https://auth.atlassian.com/oauth/token` (serve il Secret:
  Atlassian non supporta PKCE per queste app);
- `https://api.atlassian.com/oauth/token/accessible-resources` dà il `cloudId` del sito;
- le chiamate vanno a `https://api.atlassian.com/ex/jira/<cloudId>/rest/api/3/...` con
  `Authorization: Bearer <access token>` (dura circa 1 ora, solo in memoria);
- il token di rinnovo **cambia a ogni uso** (rotazione): l'app salva subito quello nuovo.
  Pagina e finestre delle issue condividono la stessa sessione, che si rinnova una volta sola.

API token:
- **Autenticazione**: HTTP Basic con `email:token`, sempre in HTTPS.
- **Token classico**: chiamate dirette a `https://quixantplc.atlassian.net/rest/api/3/...`.
- **Token con scope**: Atlassian accetta questi token solo tramite il gateway
  `https://api.atlassian.com/ex/jira/<cloudId>/rest/api/3/...`. L'app se ne accorge da sola:
  - se il sito risponde 401, legge il `cloudId` da `https://quixantplc.atlassian.net/_edge/tenant_info`;
  - poi riprova sul gateway.

Formati dei dati:
- **Ricerca**: usa `POST /rest/api/3/search/jql` con paginazione `nextPageToken`. Il vecchio
  `/rest/api/3/search` è stato rimosso da Atlassian.
- **Testi** (descrizioni, commenti): sono in formato ADF (Atlassian Document Format). L'app li
  converte in testo semplice per mostrarli e converte il testo in ADF per inviarlo.
- **Worklog**: `started` nel formato `2026-10-30T14:00:00.000+0100`; `timeSpentSeconds` calcolato
  dalle ore (1d = 8h, come nel resto dell'app).

Esecuzione e log:
- Tutte le chiamate girano in background: la finestra non si blocca.
- Il log `logs/api_sync.log` registra le chiamate come `jira /rest/api/3/...`. Non scrive
  l'header `Authorization`, quindi niente token. Per il login OAuth scrive solo l'esito
  ("scambio del codice riuscito", "rinnovo del token riuscito"): codice, Secret e token mai.

## 6. Dove sono i dati

| Cosa | Dove |
|------|------|
| API token | Gestore credenziali di Windows, voce `login_time/jira:quixantplc.atlassian.net` |
| Login Atlassian: Secret + token di rinnovo | Gestore credenziali di Windows, voce `login_time/jira-oauth:quixantplc.atlassian.net` (più `#1`, `#2`… perché il token è lungo) |
| Login Atlassian: access token | Solo in memoria (circa 1 ora) |
| Sito, email, Client ID, cloudId, modo di accesso | `jira_settings.json` nella cartella del progetto (escluso da git) |
| Issue, commenti | Solo in memoria, riletti a ogni apertura |

Su Windows il token non finisce mai in un file. Se il Gestore credenziali rifiuta la
scrittura, l'app lo usa solo per la sessione e lo segnala.

Per togliere il token da questo PC: menu ⋯ della pagina Jira → **"Dimentica il token Jira su
questo PC"**. In alternativa: Pannello di controllo → Gestione credenziali → Credenziali di
Windows. Per revocarlo del tutto: pagina dei token Atlassian → **Revoke**.

## 7. Problemi frequenti

| Messaggio | Causa probabile | Cosa fare |
|-----------|-----------------|-----------|
| "Il collegamento con Atlassian è scaduto o è stato revocato" | 90 giorni senza usare Jira dall'app, oppure accesso revocato | "Accedi con Atlassian" e rifai Microsoft + Duo |
| "La porta 53682 è occupata" | Un altro login è ancora in attesa, o un altro programma usa la porta | Chiudi l'altro login (o aspetta 5 minuti) e riprova |
| "Atlassian ha rifiutato l'app (invalid_client)" | Client ID o Secret sbagliati | Ricopiali da Settings nella developer console (link "Cambia") |
| "Accesso non autorizzato" | Hai premuto "Annulla" nella pagina Atlassian, o gli admin non permettono l'integrazione | Riprova; se persiste, chiedi agli admin Atlassian |
| "L'autorizzazione non comprende quixantplc.atlassian.net" | Al consenso è stato scelto un altro sito | Rifai il login e scegli quixantplc |
| "Jira ha rifiutato il token (HTTP 401)" | Token scaduto o revocato, oppure email diversa da quella dell'account Atlassian | Crea un nuovo token; controlla l'email (menu ⋯ → "Cambia token…") |
| "HTTP 403" | Al token manca uno scope, oppure gli admin hanno bloccato gli API token per gli account aziendali | Ricrea il token con i tre scope; se persiste, chiedi agli admin Atlassian |
| "Issue does not exist…" (404) | La issue non esiste o non hai i permessi | Aprila nel browser per verificare |
| "Jira non raggiungibile" | Rete/VPN/proxy | Verifica di aprire Jira nel browser dallo stesso PC |
| Nessuno stato in "Cambia stato" | Il workflow non permette passaggi da quello stato al tuo utente | Come in Jira web |
