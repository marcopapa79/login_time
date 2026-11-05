# login_time – Sicurezza delle credenziali

Documento di riferimento su come l'app gestisce la password e il token di accesso a
Quixant Hub (`https://support.quixant.com`) e il token di Jira Cloud
(`https://quixantplc.atlassian.net`, sezione 7). Contiene anche il confronto con l'uso dal
browser. Aggiornato al 05/11/2026.

---

## 1. In sintesi

- **Nessuna password nel codice né in git.** La vecchia password presente nella cronologia
  del repository è stata rimossa con `git filter-repo` (23/10/2026) e poi cambiata.
- **La password è salvata nel Gestore credenziali di Windows**, cifrata da Windows per il tuo
  account. Il file `credentials.json` contiene solo l'email.
- **La password non viene mai mostrata né precompilata.** Viene letta solo quando premi
  ACCEDI e resta in memoria fino a "Esci".
- **Il portale riceve la password una sola volta per sessione** (`POST /api/login`, HTTPS).
  Tutte le altre chiamate usano un **token** che vive solo in memoria e non viene mai
  scritto su disco.
- **I log mascherano** password e token (`***`).
- **Jira:** l'app non usa né salva le credenziali Microsoft. Il modo consigliato è il **login
  Atlassian nel browser con Duo** (OAuth 2.0); in alternativa un API token personale. In
  entrambi i casi i segreti stanno solo nel Gestore credenziali di Windows (sezione 7).

---

## 2. Il percorso della password

```
Login ──► Gestore credenziali di Windows ──► memoria (solo durante la sessione)
                                                 │
                                                 ▼
                                   POST https://support.quixant.com/api/login   (1 volta, HTTPS)
                                                 │
                                                 ▼
                              token Bearer in memoria ──► tutte le altre chiamate API
                                                 │
                                          "Esci" / chiusura app ──► password e token cancellati
```

### 2.1 Dove è salvata

| Cosa | Dove | Protezione |
|------|------|------------|
| Password | Gestore credenziali di Windows, voce `login_time/support.quixant.com` | Cifrata da Windows (DPAPI) con una chiave legata al tuo account Windows |
| Email | `credentials.json` nella cartella del progetto | Non è un segreto; il file è escluso da git (`.gitignore`) |
| Token del portale | Solo in memoria | Mai su disco; cancellato con "Esci" o alla chiusura |
| Ore e work log | `worklogs.json` (cartella dati, es. OneDrive) | Nessun dato di accesso al suo interno |
| Token Jira (API token Atlassian) | Gestore credenziali di Windows, voce `login_time/jira:quixantplc.atlassian.net` | Come la password; mai in un file su Windows |
| Jira, login Atlassian: Secret dell'integrazione + token di rinnovo | Gestore credenziali di Windows, voce `login_time/jira-oauth:quixantplc.atlassian.net` (+ `#1`, `#2`…) | Come la password; mai in un file su Windows |
| Jira, login Atlassian: access token | Solo in memoria (circa 1 ora) | Mai su disco |
| Sito, email, Client ID, cloudId Jira | `jira_settings.json` nella cartella del progetto | Non sono segreti; file escluso da git |

La voce è visibile ed eliminabile da **Pannello di controllo → Gestione credenziali →
Credenziali di Windows**.

Codice: `src/login_time/credentials_store.py`
- `write_credential()` – salva la password con le API di Windows `CredWriteW`
  (tipo *generic*, persistenza *local machine*, testo in UTF-16). Usa solo `ctypes`
  della libreria standard: nessun pacchetto esterno da installare o da fidarsi.
- `read_credential()` – la rilegge con `CredReadW` e libera subito la memoria di Windows (`CredFree`).
- `delete_credential()` – la cancella con `CredDeleteW`.

### 2.2 Caricamento e salvataggio

Codice: `src/login_time/config.py`
- `DEFAULT_PASSWORD = ""` – nessuna password di default nel codice.
- `load_credentials()` – legge dal Gestore credenziali. Se trova ancora una password in chiaro
  in `credentials.json` (versioni vecchie), la **sposta** nel Gestore credenziali una sola
  volta e la **toglie** dal file.
- `save_credentials()` – scrive la password nel Gestore credenziali e nel file solo l'email.
  Solo se Windows rifiutasse la scrittura, la password resterebbe nel file (git-ignored)
  come ripiego.
- `load_saved_username()` – usato all'avvio: restituisce l'email e *se* esiste una password
  salvata, senza tenerla in memoria.
- `forget_saved_password()` – cancella la password salvata (menu profilo →
  "Dimentica la password su questo PC").

### 2.3 Schermata di login

Codice: `src/login_time/ui.py`
- `_build_login_ui()` – il campo password è **sempre vuoto**. Se esiste una password salvata
  compare "✓ Password salvata: lascia il campo vuoto per usarla". Il pulsante "occhio" mostra
  solo ciò che stai scrivendo, mai la password salvata.
- `_handle_login()`
  - campo vuoto → legge la password dal Gestore credenziali **in quel momento**;
  - password scritta e diversa da quella salvata → serve "Ricorda le credenziali" per aggiornarla;
  - dopo il login il campo viene svuotato.
- Il login dell'app è un controllo **locale**; l'autenticazione vera avviene col portale.

### 2.4 Verso il portale

Codice: `src/login_time/api_client.py`, `src/login_time/ui.py`
- `DEFAULT_BASE_URL = "https://support.quixant.com"` – indirizzo **fisso** nel codice, sempre HTTPS.
- `_ensure_api_session()` – se esiste già un token lo riusa; altrimenti chiama `login()` una volta.
- `login()` / `_build_login_body()` – inviano email e password **solo** a `POST /api/login`.
- `_send()` – tutte le altre richieste portano solo `Authorization: Bearer <token>`.

### 2.5 Fine sessione

Codice: `src/login_time/ui.py`
- `_logout()` → `_clear_session_secrets()` – azzera password, token e dati di sessione in
  memoria. La copia salvata nel Gestore credenziali resta, finché non usi "Dimentica la password".
- Chiudere l'app ha lo stesso effetto: la memoria del processo viene rilasciata.

### 2.6 Log di debug

Codice: `src/login_time/api_log.py`, file `logs/api_sync.log` (escluso da git)
- `_SECRET_KEYS` / `mask_secrets()` – i campi `password`, `token`, `accessToken`, `jwt`, ecc.
  vengono scritti come `***`, anche nel formato form-encoded (`password=***`).
- La risposta di `/api/login` (che contiene il token) **non viene registrata**.
- L'header `Authorization` non viene mai scritto.

---

## 3. Confronto con l'uso del portale dal browser

| Aspetto | Portale nel browser | login_time |
|---------|--------------------|------------|
| Password salvata | Gestore password di Edge, cifrato da Windows | Gestore credenziali di Windows: **stessa protezione** |
| Sessione | Cookie **salvato su disco** nel profilo del browser, spesso valido a lungo | Token **solo in memoria**, mai su disco; sparisce con "Esci" o chiudendo l'app |
| Siti falsi (phishing) | Un link o una mail possono portare a una pagina di login contraffatta | L'indirizzo è fisso nel codice: l'app non può essere dirottata altrove |
| Estensioni e script di terzi | Le estensioni possono leggere pagine e campi password | Nessuna estensione, nessuno script esterno |
| Mostrare la password salvata | Edge la mostra dopo PIN o password di Windows | **Mai mostrata**: l'app la usa ma non la visualizza |
| Connessione | HTTPS | HTTPS (uguale) |
| Tracciabilità | Nessun log locale delle operazioni | `logs/api_sync.log` con ogni chiamata, segreti mascherati |
| Superficie d'attacco | Browser completo (rendering, plugin, JavaScript) | Poche chiamate API note, solo libreria standard Python |

**Conclusione:** per la custodia della password l'app è **sicura almeno quanto il browser**,
perché usa la stessa protezione di Windows. È **più sicura** sulla sessione (nessun cookie
persistente), sul phishing (indirizzo fisso) e sull'esposizione (password mai visualizzata,
nessuna estensione di terze parti).

---

## 4. Limiti residui

1. **PC sbloccato.** Chi usa il tuo PC con la tua sessione Windows aperta può usare l'app,
   esattamente come il browser. Blocca lo schermo con **Win+L** quando ti allontani.
2. **Programmi col tuo utente.** Il Gestore credenziali protegge dal furto di file e dagli altri
   utenti, ma un programma avviato col tuo account Windows può leggerlo (vale anche per le
   password di Edge). Per il massimo isolamento: "Dimentica la password" e scriverla a ogni
   avvio, così esiste solo in memoria.
3. **Password in memoria durante la sessione.** È necessaria per il login API; viene cancellata
   con "Esci" o alla chiusura.
4. **Tester API (menu Advanced).** Strumento per sviluppatori: il campo password non è
   precompilato e, se vuoto, usa la password della sessione.
5. **API non documentata.** Gli endpoint del portale possono cambiare; il log serve a verificare
   cosa viene inviato.

---

## 5. Come verificare

| Verifica | Come |
|----------|------|
| La password è nel Gestore credenziali | Pannello di controllo → Gestione credenziali → Credenziali di Windows → `login_time/support.quixant.com` |
| Il file non contiene la password | `credentials.json` deve contenere solo `{"username": "..."}` |
| Il log non contiene segreti | In `logs/api_sync.log` il login appare come `"password": "***"` e la risposta di login non è registrata |
| Nessuna password nel codice/git | `git log --all -p \| Select-String "<vecchia password>"` non restituisce nulla |
| Test automatici | `python -m unittest discover -s tests` (credenziali, login con campo vuoto, logout, "Dimentica", token Jira) |
| Il token Jira è nel Gestore credenziali | Credenziali di Windows → `login_time/jira:quixantplc.atlassian.net`; `jira_settings.json` deve contenere solo `site` ed `email` |

---

## 6. Se la password viene compromessa

1. Cambiala sul portale Quixant Hub.
2. Nell'app: scrivi la nuova password, spunta "Ricorda le credenziali" e premi ACCEDI
   (aggiorna il Gestore credenziali). In alternativa: menu profilo → "Dimentica la password".
3. Se fosse finita in un commit: rimuoverla dalla cronologia con `git filter-repo --replace-text`
   e fare `git push --force` (vedi la procedura usata il 23/10/2026), poi far ri-clonare il
   repository sugli altri PC.

---

## 7. Jira Cloud

### 7.1 Due modi di accesso

Nel browser l'accesso a Jira passa dal single sign-on aziendale: Microsoft → password → Duo.
L'app in nessun caso:
- chiede o salva la password Microsoft;
- intercetta i codici o le notifiche Duo;
- usa i cookie del browser.

**Login Atlassian con Duo (OAuth 2.0 3LO, consigliato).** Il login avviene nel browser,
con Microsoft + Duo, come per Jira web. Atlassian consegna all'app un access token (circa
1 ora, solo in memoria) e un token di rinnovo. Rispetto all'API token:
- **Duo resta nel giro:** senza login + Duo nessuno può creare un nuovo accesso; il token di
  rinnovo scade dopo **90 giorni senza uso** e cambia a ogni utilizzo (rotazione: un token
  rubato e già usato dall'app non vale più).
- **Portata minima:** integrazione *Resource-level* (solo `quixantplc.atlassian.net`) e solo
  gli scope `read:jira-work`, `write:jira-work`, `read:jira-user`.
- **Revoca** da id.atlassian.com → App collegate, senza toccare la password aziendale.
- Serve il **Secret** dell'integrazione (Atlassian non supporta PKCE per queste app). Il Secret
  identifica l'integrazione, non te: da solo non dà accesso a Jira senza il tuo login + Duo.
  Sta nel Gestore credenziali; se pensi che sia esposto, rigeneralo nella developer console.

Codice del login: `src/login_time/jira_oauth.py`
- `wait_for_code()`: server di ritorno **solo su 127.0.0.1:53682** (su Windows con
  `SO_EXCLUSIVEADDRUSE`, così nessun altro programma può mettersi sulla stessa porta); accetta solo
  la risposta con lo `state` casuale generato per quel login; si chiude subito dopo.
- `exchange_code()` / `refresh_tokens()`: chiamate HTTPS a `auth.atlassian.com`; il log registra
  solo l'esito, mai codice, Secret o token.
- `OAuthSession`: un solo rinnovo alla volta (lock) anche con più finestre aperte; salva subito
  il nuovo token di rinnovo (`config.save_jira_oauth_refresh`).
- `config.save_jira_oauth()`: al primo login riuscito toglie dal PC il vecchio API token.

**API token (alternativa).** Il metodo che Atlassian documenta per gli script:
- Si crea una sola volta su `id.atlassian.com`, dopo il normale login con Microsoft + Duo:
  la MFA protegge anche la creazione del token.
- Può essere limitato con gli **scope** (`read:jira-work`, `write:jira-work`, `read:jira-user`):
  in quel caso vale solo per Jira e solo per queste operazioni.
- **Scade** (al massimo dopo 365 giorni) e si **revoca** in un clic dalla pagina dei token,
  senza cambiare la password aziendale.

### 7.2 Il percorso dell'API token

```
id.atlassian.com (browser, Microsoft + Duo) ──► token copiato una volta nell'app
          │
          ▼
GET /rest/api/3/myself (verifica, HTTPS) ──► solo se va bene: Gestore credenziali di Windows
          │
          ▼
JiraClient in memoria ──► header Authorization: Basic email:token su ogni chiamata HTTPS
          │
"Esci" / chiusura app ──► client e token tolti dalla memoria (la copia salvata resta)
```

Codice:
- `src/login_time/config.py`:
  - `save_jira_settings()`: token nel Gestore credenziali (voce `login_time/jira:<sito>`), sito ed
    email in `jira_settings.json`. Su Windows, se il Gestore credenziali rifiuta la scrittura,
    **solleva un errore** invece di scrivere il token in chiaro: l'app lo usa solo per la sessione.
  - `load_jira_settings()`: all'avvio dice solo *se* un token esiste, senza tenerlo in memoria.
  - `load_jira_token()`: legge il token quando apri la pagina Jira.
  - `forget_jira_token()`: lo cancella (menu ⋯ della pagina Jira → "Dimentica il token Jira").
- `src/login_time/credentials_store.py`: le stesse funzioni della password del portale, con la
  voce (`target`) separata. Cancellare il token Jira non tocca la password del portale e viceversa.
- `src/login_time/jira_client.py`:
  - `_send()`: costruisce l'header `Authorization` e non lo passa mai al log;
  - `_auth_message()`: per 401/403 mostra un messaggio chiaro, senza ripetere il token;
  - `connect()`: prova prima il sito, poi il gateway ufficiale `api.atlassian.com` (token con scope).
    Gli indirizzi sono il sito configurato e il gateway Atlassian, sempre in HTTPS.
- `src/login_time/jira_page.py`: il campo del token è mascherato (`•`), viene svuotato dopo il
  collegamento e non è mai precompilato.

### 7.3 Confronto con Jira nel browser

| Aspetto | Jira nel browser | login_time · login Atlassian (Duo) | login_time · API token |
|---------|------------------|------------------------------------|------------------------|
| Credenziali Microsoft | Digitate nella pagina Microsoft | Digitate nella pagina Microsoft, **mai** viste dall'app | **Mai** viste né salvate dall'app |
| MFA (Duo) | A ogni nuova sessione | Al collegamento e dopo 90 giorni senza uso o revoca | Una volta, quando crei il token |
| Sessione | Cookie nel profilo del browser | Token di rinnovo (rotante) nel Gestore credenziali, access token in memoria | Token nel Gestore credenziali |
| Portata | Tutto ciò che il tuo utente può fare | Solo quixantplc, solo i 3 scope Jira | Con gli scope: solo Jira, 3 scope |
| Revoca | Logout / cambio password | App collegate / "Scollega" | "Revoke" sul token |
| Scadenza | Dipende dalla sessione SSO | 90 giorni senza uso | Fissa, al massimo 365 giorni |

### 7.4 Limiti

- Il token dà accesso a Jira con i **tuoi permessi** finché è valido: trattalo come una password.
  Se pensi che sia stato esposto, **revocalo** subito dalla pagina dei token Atlassian.
- Valgono gli stessi limiti della sezione 4: PC sbloccato, programmi avviati col tuo utente.
- Gli admin Atlassian possono disattivare gli API token per gli account aziendali, o bloccare le
  integrazioni OAuth personali. In quel caso la pagina Jira mostra l'errore e resta l'altro modo
  (o solo il browser).
- Login Atlassian: il token di rinnovo vale come una sessione del browser che dura di più (fino a
  90 giorni senza uso). Chi controlla il tuo account Windows sbloccato può usarlo, come i cookie
  del browser. "Scollega" lo cancella dal PC; App collegate lo revoca lato Atlassian.
- Le ore registrate su Jira non vanno al portale Quixant Hub (sono sistemi separati).
