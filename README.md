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

## Tests

```powershell
python -m unittest discover -s tests
```
