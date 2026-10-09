/**
 * The page's read-only state, which bpmn-js does not provide.
 *
 * A modeler is live from the moment it is constructed and the library offers no
 * read-only switch, so "not editing" is something this project builds. Every
 * command that would change the diagram is refused while the flag is off; the
 * palette and context pad are hidden by CSS in `render/template.html`, since
 * they are bpmn-js's own DOM and it puts them back whenever it likes.
 *
 * Editing is session-only and nothing is ever saved, which is what keeps an
 * edited diagram from disagreeing with the `graph.json` it came from.
 */

/**
 * Every command that changes the diagram rather than the view.
 *
 * Named individually rather than vetoed wholesale: a blanket refusal would also
 * catch the layout and resize work importing a diagram does for itself.
 */
const MUTATIONS = [
  'shape.create', 'shape.append', 'shape.delete', 'shape.move', 'shape.resize',
  'shape.attach', 'shape.replace', 'shape.toggleCollapse',
  'elements.create', 'elements.delete', 'elements.move',
  'connection.create', 'connection.delete', 'connection.reconnect',
  'connection.updateWaypoints', 'bendpoint.move',
  'element.updateLabel', 'label.create'
];

/**
 * Above the 1000 `BpmnRules` registers at, so this answers first and its
 * refusal is the one that stands.
 */
const RULE_PRIORITY = 2000;

let editing = false;

/** Turn editing on or off. The page owns the button; this owns the answer. */
export function setEditing(on) {
  editing = Boolean(on);
}

function EditGate(eventBus) {
  function veto() {
    // undefined is "no opinion", which hands the decision back to bpmn-js.
    return editing ? undefined : false;
  }

  MUTATIONS.forEach(function (command) {
    eventBus.on('commandStack.' + command + '.canExecute', RULE_PRIORITY, veto);
  });

  // Renaming is refused above, but direct editing opens on a double-click
  // rather than through a rule, so without this the box would appear and then
  // silently decline to save what was typed into it.
  eventBus.on('element.dblclick', RULE_PRIORITY, veto);
}

EditGate.$inject = ['eventBus'];

export default {
  __init__: ['pfgEditGate'],
  pfgEditGate: ['type', EditGate]
};
