/**
 * The bundle stage 3 inlines: bpmn-js plus this project's own modules.
 *
 * Built by `npm run build --prefix js` into `dist/pfg-viewer.js`, which
 * `render/assets.py` reads and inlines. The page never constructs a modeler
 * itself -- it asks for one here -- so everything bpmn-js needs to know about
 * this project lives in `src/` rather than being spread through the page
 * script.
 *
 * The stylesheets are not bundled. `render/assets.py` reads them straight from
 * `node_modules`, because Python is what assembles the page.
 */

import Modeler from 'bpmn-js/lib/Modeler';

import editGateModule, { setEditing } from './editGate';
import paletteModule from './palette';
import rendererModule from './renderer';

/**
 * A modeler wired with this project's modules.
 *
 * @param {string} container a selector for the element to draw into
 */
function createViewer(container) {
  return new Modeler({
    container: container,
    additionalModules: [editGateModule, rendererModule, paletteModule]
  });
}

// The page's whole interface to bpmn-js. Deliberately small: anything that
// needs to know how a diagram is drawn belongs in this folder, not in the
// template.
window.PFG = {
  createViewer: createViewer,
  setEditing: setEditing
};
