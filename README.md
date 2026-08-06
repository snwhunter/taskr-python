# taskr Google Sheets storage

The `db` worksheet is a header-driven task table. Its exact headers are `ID`,
`Category`, `Reference`, `Task`, `Details`, `Tags`, `Target`, `Assigned`,
`Priority`, `Status`, and `Notes`. Columns may be reordered: storage resolves
every column from row 1 before reading or writing. IDs are timestamp-based UUIDv7
values, rather than unstable row numbers or collision-prone timestamp strings.

`Target` is an ISO 8601 calendar date (`YYYY-MM-DD`). Priority is `1` (high), `2`
(medium), `3` (low), or `4` (someday). Status is `None`, `InProgress`, `Blocked`,
or `Complete`.

## Configuration and initialization

Share the spreadsheet with the Google service account, then provide configuration
through the environment (do not commit a credential JSON file):

```bash
export TASKR_SPREADSHEET_ID='...'
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/taskr/service-account.json"
# Optional: TASKR_DB_WORKSHEET=db TASKR_LOG_WORKSHEET=log
python scripts/init_sheets.py
```

Create the `db` and `log` worksheets first. The script installs their headers and
strict validation for ID non-blank, Status, and Priority. You may use Google
Sheets' UI to convert the `db` range into a table; this does not change storage
behavior. The service account requires edit access. When running on Google Cloud,
omit `GOOGLE_APPLICATION_CREDENTIALS` to use Application Default Credentials.

## Audit and partial failures

Every create, update, archive, and delete writes the task first, then appends a
`log` row containing Event ID, UTC timestamp, actor/source, operation, task ID,
and compact JSON before/after snapshots. The log is append-only; the storage API
never updates or removes log rows.

Google Sheets does not provide a transaction spanning two worksheets. If the task
write succeeds but the log append fails, the mutation raises `AuditWriteError`
instead of reporting success. The exception carries the complete `event`. A job
runner should retain it and retry `store.retry_audit(error.event)`. Retry checks
the Event ID column first, so a lost response after a successful append cannot
produce a duplicate. Monitoring `AuditWriteError` detects every partial failure;
callers should not retry the original mutation because its task write already
happened.

