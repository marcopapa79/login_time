# login_time

Simple Python desktop app with a login GUI.

## Features
- Default username: `marco.papa@quixant.com`
- Default password: `Birindelli79`
- Editable fields in the login form
- Save button to update default credentials for next runs
- Success message: `Login done`
- Dashboard welcome message: `Welcome Marco`
- Ticket opener in browser
- Local working time log table
- Add and remove working time log entries
- Per-row actions in dashboard log:
	- Open ticket in browser
	- Copy working time (local copy window)
	- Copy work log (local copy window)
- Monthly Report button (opens Quixant admin monthly report page)
- Scrollable ticket dashboard for large ticket lists

## Run
From project root:

```powershell
python main.py
```

## Notes
- Uses Tkinter (included in standard Python on Windows).
- Saved defaults are stored in `credentials.json`.
- Local working logs are stored in `worklogs.json`.
