# taskr desktop app

Taskr is a small Tk desktop client for an existing Google Sheet. Python never
receives Google credentials: it calls a spreadsheet-bound Google Apps Script web
app over HTTPS. No local task database is used. Only non-secret preferences and
autocomplete history are stored locally.

The window title includes a launch version in `YYMMDDHHmmSS` format, making the
running instance straightforward to identify in screenshots and support notes.

## Existing architecture audit

Before this implementation the repository had **no Apps Script code, web-app
route, or HTTP client**. It directly accessed a worksheet using `gspread` and a
service account/Google ADC. Its table was called `db`, permitted reordered
headers, and put `Tags` at column 5, so it did not match the required existing
Sheet contract. The only reusable conventions were timestamp UUIDv7 IDs and the
status values blank/unstarted (previously serialized as `None`), `InProgress`,
`Blocked`, and `Complete`.

The minimal API added in `apps-script/Code.gs` has one diagnostic `GET` route and
one JSON `POST` route with these actions:

* `list` — returns every populated task row;
* `create` — validates and appends an exact 11-field row;
* `update` — replaces an identified row (an omitted `Tags` value is preserved);
* `complete` — changes only `Status` to `Complete`.

The Sheet remains the source of truth and must be named `Tasks`, with these exact
headers in row 1 and exact order:

`ID, Category, Reference, Task, Details, Target, Assigned, Priority, Status, Notes, Tags`

## Deploy the Apps Script

1. Open the spreadsheet and choose **Extensions → Apps Script**.
2. Copy `apps-script/Code.gs` into the bound script project and save it.
3. Choose **Deploy → New deployment → Web app**. Execute as the script owner and
   choose the access setting appropriate for the users of this desktop app.
4. Copy the deployment `/exec` URL. Deploy a new version after every server-code
   change; merely saving Apps Script does not update an existing deployment.

Apps Script validates the existing header rather than creating, renaming, or
reordering columns. `Tags` must contain a JSON object. Updates sent by this app
round-trip the existing dictionary, preserving all keys.

## Configure and run

Python 3.11+ and Tk are required. Install and run:

```bash
python -m pip install -e .
export TASKR_API_URL='https://script.google.com/macros/s/.../exec'
export TASKR_USER='your-name'
python -m taskr
```

Alternatively create `~/.config/taskr/config.json`:

```json
{
  "api_url": "https://script.google.com/macros/s/.../exec",
  "user": "your-name",
  "categories": [],
  "references": [],
  "assigned": []
}
```

Use **Add Tasks** to open the task-entry popup. There is no separate submit
button: selecting EOD, EOW, EOM, a future date, or no date creates the task.
Category, Reference, and Assigned histories are saved to the config file for the
editable autocomplete boxes. Category and Reference are prefilled when the
active view has an unambiguous filter for them. The optional Parent pull-down
stores the chosen task's ID in Tags. Newly created tasks have blank Priority,
Status, and Notes and provenance in Tags.

The app starts with five task views. The **+ View**, **− View**, and **Rename**
controls are grouped across the top. Click the dropdown marker in any table
heading to search and select that column's visible values; filters from multiple
columns are combined. Each tab's name and column selections are remembered in
`config.json`. Double-click a table cell to edit it, or select a row and use
**Complete task**. **Set parent…** stores the selected parent ID in the child's
`Tags` object. A parent can be chosen from its row or the pull-down, and visible
children are nested below their parent. Task, Details, and Notes remain
left-aligned while the other columns are centered.
