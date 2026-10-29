# Quixant Hub – ticket API used by login_time

Captured from the portal's own ticket page (`/ticket/Edit/<code>`, Edge DevTools → Network,
29/10/2026). All calls go to `https://support.quixant.com/api/` with the Bearer token from
`POST /api/login`. Every request the app sends is written to `logs/api_sync.log`.

## Identifiers

| Value | Where it comes from |
|-------|---------------------|
| Ticket uuid (`ba8175aa-…`) | `GET tickets/list2` → item with `internal_id` = code (exact match only), cached in `ticket_uuid_cache.json` |
| Numeric ticket id (`3304`) | `GET tickets/select/{uuid}` → `form.id_ticket` |
| idCompany (Quixant) | `GET companies` → item with `identifier: "QUIX"` (`system: true`) |
| New message uuid | `GET tickets/newguid` → `guid` |

## Working hours

| Action | Call |
|--------|------|
| Create | `POST working_hours/form` `{TicketId, Username, MonthDisplacement, Reason, WorkingTime}` → returns the entry **Id** (string) |
| Update | same call **plus `Id`** → the existing entry is modified (no duplicate) |
| Delete | `GET working_hours/delete?uuid=<Id>` |
| List per ticket | `GET working_hours/list?ticketGuid=` → `[{Id, Username, FullName, Month, WorkingTime, Reason, TicketId}]` |
| Totals per ticket | `GET tickets/get_times?ticketGuid=` → `working_times` (entries + hours of messages) and `extra_times` per month/person |

The app stores the returned Id in `api_entry_id`. Rows synced before that are linked by
"Confronta col portale" (same user, month, hours and reason).

## Ticket messages

| Action | Call |
|--------|------|
| List | `GET ticket_posts/list?page=1&uuid=<ticket uuid>&idCompany=<Quixant uuid>` → 10 posts per page: `uuid, fullname, post_date, text (HTML), public, time_spent, appAttachments`. Working-hours entries appear as posts with `id_ticket_post = -1` |
| Create | `POST ticket_posts/create` (form-encoded) `uuid, id_ticket, text (HTML), attachments="", public ("false" = internal note, "true" = reply to customer, emailed), time_spent ("1h")` → `{new_post_uuid, mail_enqueue, mail_error}` |
| Update / delete | `POST ticket_posts/update`, `POST ticket_posts/delete?uuid=` (not used by the app) |

Hours sent with a message are counted in `get_times` but are not a `working_hours` entry:
the app marks those rows with `api_post_uuid` and edits them only locally.
