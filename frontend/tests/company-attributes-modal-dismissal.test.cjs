const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.resolve(__dirname, "../../static/js/projects/company-attributes.js"),
  "utf8"
);
const modalTemplate = fs.readFileSync(
  path.resolve(__dirname, "../../apps/projects/templates/projects/partials/company_attributes_modals.html"),
  "utf8"
);

function sourceBetween(startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.notEqual(start, -1, `Missing source marker: ${startMarker}`);
  assert.notEqual(end, -1, `Missing source marker: ${endMarker}`);
  return source.slice(start, end);
}

function loadDefinitionState() {
  const helperSource = sourceBetween(
    "function definitionItems(items)",
    "function managerHasUnsavedChanges()"
  );
  return Function(`${helperSource}\nreturn definitionState;`)();
}

function loadValueFieldsState() {
  const helperSource = sourceBetween(
    "function valueFieldsState(fields)",
    "function valuesFormState()"
  );
  return Function(`${helperSource}\nreturn valueFieldsState;`)();
}

function attributeFixture(overrides = {}) {
  return {
    id: 12,
    client_id: null,
    name: "Plan",
    type: "single_select",
    position: 0,
    settings: {},
    options: [
      {
        id: 21,
        client_id: null,
        label: "Pro",
        position: 0,
        color: { text: "#111111", bg: "#eeeeee", border: "#dddddd" },
      },
    ],
    ...overrides,
  };
}

test("definition dirty state is reversible and covers definition edits", () => {
  const definitionState = loadDefinitionState();
  const baseline = [attributeFixture(), attributeFixture({ id: 13, name: "Owner", type: "text", options: [] })];
  const draft = JSON.parse(JSON.stringify(baseline));
  const initialState = definitionState(baseline);

  assert.equal(definitionState(draft), initialState);
  draft[0].name = "Tier";
  assert.notEqual(definitionState(draft), initialState);
  draft[0].name = "Plan";
  assert.equal(definitionState(draft), initialState);

  draft.push(attributeFixture({ id: null, client_id: "attribute-new", name: "" }));
  assert.notEqual(definitionState(draft), initialState);
  draft.pop();
  assert.equal(definitionState(draft), initialState);

  draft.reverse();
  assert.notEqual(definitionState(draft), initialState);
  draft.reverse();
  draft[0].options[0].label = "Enterprise";
  assert.notEqual(definitionState(draft), initialState);
});

test("company value dirty state compares the current controls with the opening snapshot", () => {
  const valueFieldsState = loadValueFieldsState();
  const fields = [
    { dataset: { valueAttribute: "12" }, value: "Pro" },
    { dataset: { valueAttribute: "13" }, value: "" },
  ];
  const initialState = valueFieldsState(fields);

  fields[1].value = "New owner";
  assert.notEqual(valueFieldsState(fields), initialState);
  fields[1].value = "";
  assert.equal(valueFieldsState(fields), initialState);

  fields[1].validity = { badInput: true };
  assert.notEqual(valueFieldsState(fields), initialState);
  fields[1].validity.badInput = false;
  assert.equal(valueFieldsState(fields), initialState);
});

test("both editor backdrops and close controls use the guarded close paths", () => {
  const clickSource = sourceBetween(
    'root.addEventListener("click"',
    'searchInput.addEventListener("input"'
  );

  assert.match(clickSource, /event\.target\.matches\("\.company-attributes-modal-overlay"\)/);
  assert.match(clickSource, /modalElement === valuesModal\) requestValuesClose\(\)/);
  assert.match(clickSource, /modalElement === managerModal\) requestManagerClose\(\)/);
  assert.match(clickSource, /data-attributes-manager-close[\s\S]*requestManagerClose\(\)/);
  assert.match(clickSource, /data-company-values-close[\s\S]*requestValuesClose\(\)/);
  assert.doesNotMatch(clickSource, /event\.target\.closest\("\.company-attributes-modal-overlay"\)/);
});

test("clean editors close directly while dirty editors open the confirmation", () => {
  const managerCloseSource = sourceBetween(
    "function requestManagerClose()",
    "function requestValuesClose()"
  );
  const valuesCloseSource = sourceBetween(
    "function requestValuesClose()",
    "function confirmDiscardChanges()"
  );
  const managerDirtySource = sourceBetween(
    "function managerHasUnsavedChanges()",
    "function openManager(selectNew)"
  );

  assert.match(managerCloseSource, /managerHasUnsavedChanges\(\)\) openDiscardConfirmation\("manager"\)/);
  assert.match(managerCloseSource, /managerModal\.hasAttribute\("data-closing"\)/);
  assert.match(managerCloseSource, /else discardManager\(\)/);
  assert.match(valuesCloseSource, /valuesHaveUnsavedChanges\(\)\) openDiscardConfirmation\("values"\)/);
  assert.match(valuesCloseSource, /valuesModal\.hasAttribute\("data-closing"\)/);
  assert.match(valuesCloseSource, /else discardValues\(\)/);
  assert.match(managerDirtySource, /pendingOption && pendingOption\.value !== ""/);
  assert.match(managerDirtySource, /definitionState\(drafts\) !== definitionState\(attributes\)/);
  assert.match(source, /initialValuesState = valuesFormState\(\);[\s\S]*openModal\(valuesModal, valuesDialog\)/);
});

test("confirmation actions keep edits or discard only the selected editor", () => {
  const confirmationSource = sourceBetween(
    "function openDiscardConfirmation(target)",
    "function collectValues()"
  );
  const keydownSource = sourceBetween(
    "function trapModalKeydown(event)",
    'root.addEventListener("click"'
  );

  assert.match(modalTemplate, /role="alertdialog"/);
  assert.match(modalTemplate, />Discard unsaved changes\?</);
  assert.match(modalTemplate, /data-attributes-keep-editing>Keep editing</);
  assert.match(modalTemplate, /data-attributes-discard-changes>Discard changes</);
  assert.match(source, /data-attributes-keep-editing[\s\S]*closeDiscardConfirmation\(\)/);
  assert.match(source, /data-attributes-discard-changes[\s\S]*confirmDiscardChanges\(\)/);
  assert.match(confirmationSource, /dialogLastFocused\.get\(sourceDialog\)/);
  assert.match(source, /root\.addEventListener\("focusin"[\s\S]*dialogLastFocused\.set/);
  assert.match(confirmationSource, /const target = pendingDiscard;[\s\S]*closeDiscardConfirmation\(\);[\s\S]*target === "manager"\) discardManager\(\)[\s\S]*target === "values"\) discardValues\(\)/);
  assert.match(keydownSource, /modalElement === discardModal\) closeDiscardConfirmation\(\)/);
});
