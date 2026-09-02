# Extra Off API Manual

## Purpose

Use this flow to add annual leave, sick leave, or other `OFF` entries that must appear in Quixant Hub Monthly Report under `Miscellaneous (TRR "Day Off") - GC`.

## Verified Request Flow

The portal creates a server-side GUID before inserting a new extra-hours record.

1. Authenticate through `POST /api/login`.
2. Request a new entry identifier with `GET /api/tickets/newguid`.
3. Read the `guid` value from the response.
4. Send `POST /api/extrahours/add` with this JSON payload:

```json
{
  "uuid": "<guid returned by /api/tickets/newguid>",
  "id_clockify_task": "652434fef8763231c98909ee",
  "hours": 4,
  "log_date_start": "01/09/2026",
  "log_date_end": "01/09/2026",
  "description": "Annual leave"
}
```

`id_clockify_task` must correspond to the selected leave type. For `Annual Leave`, the verified ID is `652434fef8763231c98909ee`.

## Important Rules

- Do not send an empty `uuid` for a new extra-off entry. The API may return success, but the entry may not appear in Monthly Report.
- `uuid` is the new record GUID from `/api/tickets/newguid`; it is not the Clockify user UUID.
- Send `log_date_start` and `log_date_end` in `dd/mm/yyyy` format.
- Use the lowercase field names shown above. They mirror the Quixant Hub `/admin/ExtraHours` page JavaScript.
- A response containing `This entry is locked` means that an entry already exists for that date/type; do not create a duplicate.

## Verification

After a successful request, open Monthly Report for the matching month. The hours should appear under `Miscellaneous (TRR "Day Off") - GC` and contribute to `Total/Resource`.
