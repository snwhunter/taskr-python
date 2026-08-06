/** Spreadsheet-bound API used by the desktop app. */
const TASK_SHEET = 'Tasks';
const TASK_COLUMNS = ['ID', 'Category', 'Reference', 'Task', 'Details', 'Target',
  'Assigned', 'Priority', 'Status', 'Notes', 'Tags'];
const STATUSES = ['', 'InProgress', 'Blocked', 'Complete'];

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return json_({ok: true, data: {service: 'taskr', actions: ['list', 'create', 'update', 'complete']}});
}

function doPost(e) {
  try {
    const input = JSON.parse(e.postData.contents || '{}');
    const handlers = {list: listTasks_, create: createTask_, update: updateTask_, complete: completeTask_};
    if (!handlers[input.action]) throw new Error('Unknown action: ' + input.action);
    return json_({ok: true, data: handlers[input.action](input)});
  } catch (error) {
    return json_({ok: false, error: String(error.message || error)});
  }
}

function sheet_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(TASK_SHEET);
  if (!sheet) throw new Error('Missing worksheet: ' + TASK_SHEET);
  const headers = sheet.getRange(1, 1, 1, TASK_COLUMNS.length).getDisplayValues()[0];
  if (headers.join('\u001f') !== TASK_COLUMNS.join('\u001f'))
    throw new Error('Tasks headers must exactly match: ' + TASK_COLUMNS.join(', '));
  return sheet;
}

function rows_() {
  const sheet = sheet_();
  if (sheet.getLastRow() < 2) return [];
  return sheet.getRange(2, 1, sheet.getLastRow() - 1, TASK_COLUMNS.length).getDisplayValues()
    .filter(row => row[0]).map(row => Object.fromEntries(TASK_COLUMNS.map((name, i) => [name, row[i]])));
}

function listTasks_() { return rows_(); }

function normalize_(record) {
  const result = {};
  TASK_COLUMNS.forEach(name => result[name] = String(record[name] == null ? '' : record[name]));
  if (!result.ID) throw new Error('ID is required');
  if (!result.Task.trim()) throw new Error('Task is required');
  if (!STATUSES.includes(result.Status)) throw new Error('Invalid Status');
  JSON.parse(result.Tags || '{}');
  return result;
}

function createTask_(input) {
  const task = normalize_(input.task || {});
  if (rows_().some(row => row.ID === task.ID)) throw new Error('Duplicate ID: ' + task.ID);
  sheet_().appendRow(TASK_COLUMNS.map(name => task[name]));
  return task;
}

function updateTask_(input) {
  const sheet = sheet_();
  const values = rows_();
  const index = values.findIndex(row => row.ID === input.id);
  if (index < 0) throw new Error('Task not found: ' + input.id);
  const old = values[index];
  const changes = input.changes || {};
  if (changes.ID && changes.ID !== input.id) throw new Error('ID cannot change');
  // Tags are opaque provenance. Omission preserves them; replacement is explicit.
  const updated = normalize_(Object.assign({}, old, changes, {ID: old.ID,
    Tags: Object.prototype.hasOwnProperty.call(changes, 'Tags') ? changes.Tags : old.Tags}));
  sheet.getRange(index + 2, 1, 1, TASK_COLUMNS.length).setValues([TASK_COLUMNS.map(name => updated[name])]);
  return updated;
}

function completeTask_(input) { return updateTask_({id: input.id, changes: {Status: 'Complete'}}); }
