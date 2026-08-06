const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.resolve(__dirname, "../../static/js/projects/company-attributes.js"),
  "utf8"
);
const styles = fs.readFileSync(
  path.resolve(__dirname, "../../static/css/projects/company-attributes.css"),
  "utf8"
);

function sourceBetween(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1, `Missing source marker: ${startMarker}`);
  assert.notEqual(end, -1, `Missing source marker: ${endMarker}`);
  return source.slice(start, end);
}

test("attribute rows are draggable without reserving layout space for the grip", () => {
  const listSource = sourceBetween(
    "function renderManagerList()",
    "function fieldErrorHtml(key, field)"
  );
  const dragSource = sourceBetween(
    'managerList.addEventListener("dragstart"',
    'managerList.addEventListener("dragover"'
  );

  assert.match(listSource, /data-draft-key=.*draggable="true"/);
  assert.doesNotMatch(listSource, /class="attribute-reorder-handle" draggable=/);
  assert.match(dragSource, /closest\('\[data-draft-key\]\[draggable="true"\]'/);
  assert.match(styles, /\.attribute-reorder-handle\s*{[^}]*position:\s*absolute;/s);
  assert.match(styles, /\.attribute-reorder-handle\s*{[^}]*opacity:\s*0;/s);
  assert.match(styles, /\.attribute-list-entry:hover \.attribute-reorder-handle,[\s\S]*\.attribute-list-entry:focus-within \.attribute-reorder-handle,[\s\S]*\.attribute-list-entry-dragging \.attribute-reorder-handle\s*{[^}]*opacity:\s*1;/);
});
