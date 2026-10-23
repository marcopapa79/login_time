# Riallineare un PC all'ultimo commit (cancella e riscarica)

Questa procedura butta via la copia locale del repository e la sostituisce con un clone pulito di `origin/main`.
I dati locali (`worklogs.json`, `ticket_uuid_cache.json`, `credentials.json`) vengono salvati prima e ricopiati alla fine.

> Esegui tutti i comandi in PowerShell.
> Sostituisci `C:\My_Designs\login_time` con il percorso reale della cartella, se è diverso.

---

## 0. Prima di iniziare: l'ultimo commit è davvero su GitHub?

Il nuovo clone scarica solo ciò che è già stato **pushato**.
Se sull'altro PC ci sono modifiche non ancora committate (per esempio `.gitignore` e `README.md` aggiornati), lì serve prima:

```powershell
cd C:\My_Designs\login_time
git add .gitignore README.md
git commit -m "Stop tracking local data files"
git push
```

Se `git push` viene rifiutato perché le storie sono divergenti, **non** usare `--force` senza aver controllato il passo 1 su entrambi i PC.

---

## 1. Controlla di non perdere commit locali

Sul PC da riallineare:

```powershell
cd C:\My_Designs\login_time
git fetch origin
git log --oneline origin/main..main
```

- **Nessun output**: questo PC non ha commit solo suoi, puoi procedere.
- **Compaiono dei commit**: esistono solo qui e andranno persi con il nuovo clone. Annota gli hash.
  Puoi recuperarli dopo il clone (passo 5) con `git cherry-pick`, oppure decidere di scartarli.

---

## 2. Salva i dati locali fuori dal repository

```powershell
cd C:\My_Designs\login_time
$bk = "$env:USERPROFILE\login_time_backup_$(Get-Date -Format yyyyMMdd_HHmm)"
New-Item -ItemType Directory $bk | Out-Null
Copy-Item worklogs.json, ticket_uuid_cache.json, credentials.json $bk -ErrorAction SilentlyContinue
Get-ChildItem $bk
```

Controlla che l'elenco mostri i file attesi. Annota il percorso di `$bk`.

> Se anche l'altro PC ha un `worklogs.json` con righe diverse, decidi ora quale tenere (o uniscili a mano).
> Dopo questa procedura i JSON non verranno più sincronizzati da Git.

---

## 3. Leggi l'URL del repository

```powershell
git remote get-url origin
```

Copia l'URL che compare: serve al passo 4.

---

## 4. Metti da parte la vecchia cartella e clona da zero

Rinominare è più sicuro che cancellare subito: se qualcosa va storto hai ancora tutto.

```powershell
cd C:\My_Designs
Rename-Item login_time login_time_OLD
git clone <URL-COPIATO-AL-PASSO-3> login_time
cd login_time
git log --oneline -n 5
```

Verifica che il primo commit dell'elenco sia quello atteso, cioè l'ultimo pushato.

---

## 5. (Solo se servono) Recupera i commit annotati al passo 1

```powershell
git remote add old C:\My_Designs\login_time_OLD
git fetch old
git cherry-pick <hash1> <hash2>
git remote remove old
git push
```

---

## 6. Ricopia i dati locali

```powershell
Copy-Item "$bk\*.json" C:\My_Designs\login_time\
git status
```

`git status` **non** deve elencare i file JSON: se compaiono, `.gitignore` non è aggiornato in quel commit e bisogna tornare al passo 0.

---

## 7. Ricrea l'ambiente e prova l'app

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\login_time.bat
```

---

## 8. Pulizia finale

Quando hai verificato che l'app funziona e i dati ci sono:

```powershell
Remove-Item -Recurse -Force C:\My_Designs\login_time_OLD
```

Conserva per qualche giorno la cartella di backup del passo 2.
