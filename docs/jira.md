# login_time – Pagina Jira

La pagina **Jira** (selettore "Ore · Hub | Jira" in alto, oppure Ctrl+1 / Ctrl+2) mostra le
issue di Jira Cloud (`https://quixantplc.atlassian.net`) senza aprire il browser.
Aggiornato al 30/10/2026.

---

## 1. Perché un token e non il login Microsoft + Duo

Nel browser entri in Jira con il single sign-on aziendale: Microsoft, poi password, poi Duo
sul cellulare. Quel flusso è pensato per un browser e l'app non lo replica: non legge né
salva la password Microsoft e non tocca Duo.

Atlassian prevede un altro accesso per i programmi: un **API token personale**.
- Lo crei **una volta** nel browser, dopo il normale login Microsoft + Duo.
- Ha gli stessi permessi del tuo utente Jira (o meno, se scegli gli scope).
- Scade (al massimo dopo 365 giorni) e lo puoi revocare quando vuoi.
- L'app lo salva nel Gestore credenziali di Windows, come la password del portale.

## 2. Creare il token (una volta)

1. Nella pagina Jira dell'app premi **"Apri la pagina dei token ↗"**. Si apre
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

## 3. Cosa si può fare

| Funzione | Dove | API Jira |
|----------|------|----------|
| Elenco issue: Da fare / Completate (30 gg) / Segnalate da me / Che seguo | Pagina Jira | `POST /rest/api/3/search/jql` |
| Filtro veloce per chiave o titolo | Campo "Filtra" | (locale) |
| Dettagli, descrizione, commenti | Clic su una issue | `GET /issue/{key}`, `GET /issue/{key}/comment` |
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

## 4. Dettagli tecnici

Codice:
- `src/login_time/jira_client.py`: client REST v3, solo libreria standard Python;
- `src/login_time/jira_page.py`: pagina e finestra della issue;
- `src/login_time/config.py`: `load_jira_settings`, `save_jira_settings`, `forget_jira_token`.

Come si collega:
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
  l'header `Authorization`, quindi niente token.

## 5. Dove sono i dati

| Cosa | Dove |
|------|------|
| API token | Gestore credenziali di Windows, voce `login_time/jira:quixantplc.atlassian.net` |
| Sito ed email | `jira_settings.json` nella cartella del progetto (escluso da git) |
| Issue, commenti | Solo in memoria, riletti a ogni apertura |

Su Windows il token non finisce mai in un file. Se il Gestore credenziali rifiuta la
scrittura, l'app lo usa solo per la sessione e lo segnala.

Per togliere il token da questo PC: menu ⋯ della pagina Jira → **"Dimentica il token Jira su
questo PC"**. In alternativa: Pannello di controllo → Gestione credenziali → Credenziali di
Windows. Per revocarlo del tutto: pagina dei token Atlassian → **Revoke**.

## 6. Problemi frequenti

| Messaggio | Causa probabile | Cosa fare |
|-----------|-----------------|-----------|
| "Jira ha rifiutato il token (HTTP 401)" | Token scaduto o revocato, oppure email diversa da quella dell'account Atlassian | Crea un nuovo token; controlla l'email (menu ⋯ → "Cambia token…") |
| "HTTP 403" | Al token manca uno scope, oppure gli admin hanno bloccato gli API token per gli account aziendali | Ricrea il token con i tre scope; se persiste, chiedi agli admin Atlassian |
| "Issue does not exist…" (404) | La issue non esiste o non hai i permessi | Aprila nel browser per verificare |
| "Jira non raggiungibile" | Rete/VPN/proxy | Verifica di aprire Jira nel browser dallo stesso PC |
| Nessuno stato in "Cambia stato" | Il workflow non permette passaggi da quello stato al tuo utente | Come in Jira web |
