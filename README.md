# login_time

Desktop app (Python + Tkinter, Windows) to log working time on Quixant support tickets
locally and sync it to Quixant Hub (`https://support.quixant.com`) through its API.

## Features
- Dashboard per month: target hours (Italian working days × 8h), logged work, Extra Off,
  synced / pending / missing hours, OK/CHECK status
- Month picker (any past month) with a marker on months that still have pending rows
- Ticket cards grouped by ticket, collapsible, with filters (all / pending / synced / Extra Off) and search
- One "New entry" dialog for work, Extra Off (date range → one row per working day),
  QxSupport and tickets already on the portal
- Background API sync (per row, per ticket, per month) with progress and cancel
- Warning before re-sending a row that was edited after being synced (the portal would get a duplicate)
- Import of QxSupport hours for the selected month
- Advanced: API tester for the portal endpoints (profile menu)

## Run
From the project root:

```powershell
python main.py
```

or double-click `login_time.bat`.

## Credentials
- Nothing is hard-coded. On first login type your portal email and password;
  with "Ricorda le credenziali" checked the password is stored in
  **Windows Credential Manager** (entry `login_time/support.quixant.com`) and
  `credentials.json` keeps only the email.
- On systems without Credential Manager the password falls back to `credentials.json`
  (git-ignored).

## Files
- `worklogs.json` – local worklog rows
- `ticket_uuid_cache.json` – ticket code → portal UUID cache
- `docs/DESIGN_BRIEF.md` – UI brief and rationale of the technical choices
- `docs/extra-off-api.md` – verified Extra Off API flow

## Local data
`worklogs.json`, `ticket_uuid_cache.json` and `credentials.json` are git-ignored:
Git does not sync them.

### Choosing the data folder (per PC)
Each PC chooses where `worklogs.json` and `ticket_uuid_cache.json` live with a
git-ignored `local_settings.json` in the project root (see `local_settings.example.json`):

```json
{ "data_dir": "G:\\Il mio Drive\\login_time_data" }
```

- Any folder works: local (`C:\\Data\\login_time`), OneDrive (`%OneDriveCommercial%\\login_time_data`),
  Google Drive, Dropbox, network share. `%VAR%` and relative paths (to the project root) are allowed.
- Without the file (or with an empty `data_dir`) the project folder is used.
- The `LOGIN_TIME_DATA_DIR` environment variable, if set, overrides the file.
- `credentials.json` always stays in the project folder.

To share data between PCs, point each PC's `data_dir` at the same synced folder and copy
the most recent JSON files there once (app closed). Do not keep the app open on two PCs
at the same time: the sync client would create a conflict copy instead of merging.

Commit `7c22c14` stopped tracking the two JSON files, so pulling it on a clone
that still had them deletes them from disk. Restore them with:

```powershell
git restore --source=7c22c14~1 --worktree -- worklogs.json ticket_uuid_cache.json
```

## Tests

```powershell
python -m unittest discover -s tests
```
