# Configurare la cartella dei dati

L'app salva `worklogs.json` e `ticket_uuid_cache.json` nella cartella dati scelta per il PC. Le credenziali restano invece in `credentials.json` nella cartella del progetto.

Il file si chiama **`local_settings.json`** (con la `s` finale in `settings`), si trova nella cartella principale del progetto ed è escluso da Git: la configurazione può quindi essere diversa su ogni PC.

## Creare o aggiornare `local_settings.json`

1. Chiudi l'app.
2. Apri PowerShell nella cartella del progetto, per esempio:

   ```powershell
   cd C:\My_Designs\login_time
   ```

3. Se il file non esiste ancora, crealo copiando il modello:

   ```powershell
   Copy-Item .\local_settings.example.json .\local_settings.json
   ```

   Se esiste già, aprilo per modificarlo senza sovrascriverlo:

   ```powershell
   notepad .\local_settings.json
   ```

4. Imposta `data_dir` sul percorso della cartella in cui vuoi conservare i dati. Per OneDrive, puoi usare la variabile d'ambiente `%OneDrive%`:

   ```json
   {
     "data_dir": "%OneDrive%\\login_time_data"
   }
   ```

   Oppure indica un percorso assoluto. In JSON ogni barra rovesciata va raddoppiata:

   ```json
   {
     "data_dir": "C:\\Users\\NOME_UTENTE\\OneDrive\\login_time_data"
   }
   ```

   Sostituisci `NOME_UTENTE` con il nome effettivo della cartella utente. Per Google Drive, Dropbox o un disco di rete, inserisci il relativo percorso assoluto nello stesso formato.

5. Salva il file e controlla che il percorso OneDrive esista. In PowerShell:

   ```powershell
   $env:OneDrive
   Test-Path "$env:OneDrive\login_time_data"
   ```

   Il primo comando mostra il percorso OneDrive configurato; il secondo restituisce `True` se la cartella esiste. Se la variabile è vuota, controlla il percorso di OneDrive in Esplora file e usa quel percorso assoluto nel JSON.

6. Avvia di nuovo l'app. Per verificare che il JSON sia valido puoi eseguire:

   ```powershell
   Get-Content .\local_settings.json -Raw | ConvertFrom-Json
   ```

## Spostare dati già esistenti

Cambiare `data_dir` **non sposta né unisce** i dati già presenti: l'app inizierà a leggere dalla nuova cartella, che potrebbe apparire vuota.

Prima di cambiare percorso, chiudi l'app e copia nella nuova cartella i file esistenti `worklogs.json` e `ticket_uuid_cache.json`. Non sovrascrivere una copia più aggiornata: confronta i file e scegli consapevolmente quale conservare. `credentials.json` non va spostato.

Per condividere i dati tra PC, configura su ciascun PC lo stesso percorso sincronizzato. Non tenere l'app aperta contemporaneamente su due PC: OneDrive e gli altri servizi di sincronizzazione non uniscono le modifiche ai file JSON.

## Priorità e comportamento predefinito

- Se è impostata la variabile d'ambiente `LOGIN_TIME_DATA_DIR`, questa prevale su `data_dir`.
- Se `local_settings.json` manca o `data_dir` è vuoto, l'app usa la cartella del progetto.
- I percorsi relativi in `data_dir` sono risolti a partire dalla cartella del progetto.
- `local_settings.json` e i file di dati locali non vengono sincronizzati da Git.