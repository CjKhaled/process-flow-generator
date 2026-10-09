/**
 * The shapes this project draws differently from stock BPMN.
 *
 * Two of them, and no more. Events become horizontal ovals, so the entry and
 * the exits read as terminators the way they do in an ordinary flowchart rather
 * than as small circles. A collapsed subprocess gains a vertical bar inside each
 * edge, which is the long-standing flowchart mark for "this box stands for work
 * described elsewhere" -- exactly what a collapsed subprocess is here.
 *
 * Everything else falls through to bpmn-js. `canRender` is deliberately narrow:
 * a renderer that claimed more would have to reimplement more, and the default
 * renderer is better at drawing BPMN than we are.
 *
 * Colour is not decided here. It is read from the diagram with `getFillColor`
 * and `getStrokeColor`, which consult the `color:` attributes `bpmn/colors.py`
 * writes into the file -- so the page and any other BPMN tool agree, and there
 * is one place colour is chosen rather than two.
 */

import BaseRenderer from 'diagram-js/lib/draw/BaseRenderer';
import { componentsToPath } from 'diagram-js/lib/util/RenderUtil';
import { append as svgAppend, attr as svgAttr, create as svgCreate } from 'tiny-svg';

import { getFillColor, getStrokeColor } from 'bpmn-js/lib/draw/BpmnRenderUtil';
import { is } from 'bpmn-js/lib/util/ModelUtil';

/** Above the 1000 the default renderer registers at, so this is asked first. */
const PRIORITY = 1500;

const DEFAULT_FILL = 'white';
const DEFAULT_STROKE = 'black';
const STROKE_WIDTH = 2;

/**
 * How far inside each vertical edge a subprocess's bar sits.
 *
 * Exactly bpmn-js's `TASK_BORDER_RADIUS`. At any smaller inset the bar would
 * meet the rounded corner rather than the straight top and bottom edges, and
 * poke out of the shape at both ends.
 */
const BAR_INSET = 10;

function isEvent(element) {
  return is(element, 'bpmn:StartEvent') || is(element, 'bpmn:EndEvent');
}

export class PfgRenderer extends BaseRenderer {
  constructor(eventBus, bpmnRenderer) {
    super(eventBus, PRIORITY);
    this.bpmnRenderer = bpmnRenderer;
  }

  canRender(element) {
    // labelTarget marks an element that *is* a label rather than a shape. One
    // belonging to an event would otherwise be drawn as a second oval.
    return !element.labelTarget && (isEvent(element) || is(element, 'bpmn:SubProcess'));
  }

  drawShape(parentGfx, element) {
    if (isEvent(element)) {
      return this.drawEvent(parentGfx, element);
    }
    return this.drawSubProcess(parentGfx, element);
  }

  /** A horizontal oval filling the shape's bounds. */
  drawEvent(parentGfx, element) {
    const ellipse = svgCreate('ellipse');

    // Half a stroke in from each edge, so the outline sits inside the bounds
    // rather than straddling them -- which is what keeps a re-aimed arrow
    // meeting the line it appears to meet.
    svgAttr(ellipse, {
      cx: element.width / 2,
      cy: element.height / 2,
      rx: element.width / 2 - STROKE_WIDTH / 2,
      ry: element.height / 2 - STROKE_WIDTH / 2,
      fill: getFillColor(element, DEFAULT_FILL),
      stroke: getStrokeColor(element, DEFAULT_STROKE),
      strokeWidth: STROKE_WIDTH
    });

    svgAppend(parentGfx, ellipse);
    return ellipse;
  }

  /** bpmn-js's own box, with a bar drawn inside each vertical edge. */
  drawSubProcess(parentGfx, element) {
    const shape = this.bpmnRenderer.drawShape(parentGfx, element);
    const stroke = getStrokeColor(element, DEFAULT_STROKE);

    [BAR_INSET, element.width - BAR_INSET].forEach(function (x) {
      const bar = svgCreate('line');

      svgAttr(bar, {
        x1: x,
        y1: 0,
        x2: x,
        y2: element.height,
        stroke: stroke,
        strokeWidth: STROKE_WIDTH
      });

      svgAppend(parentGfx, bar);
    });

    return shape;
  }

  /**
   * The outline connections are cropped against.
   *
   * Without this an arrow would stop at the bounding box's corner rather than
   * at the oval, leaving a visible gap on the diagonals. bpmn-js's own
   * `getCirclePath` does the same job for a circle; this is that, with two
   * radii instead of one.
   */
  getShapePath(shape) {
    if (!isEvent(shape)) {
      return this.bpmnRenderer.getShapePath(shape);
    }

    const rx = shape.width / 2;
    const ry = shape.height / 2;
    const cx = shape.x + rx;
    const cy = shape.y + ry;

    return componentsToPath([
      ['M', cx, cy],
      ['m', 0, -ry],
      ['a', rx, ry, 0, 1, 1, 0, 2 * ry],
      ['a', rx, ry, 0, 1, 1, 0, -2 * ry],
      ['z']
    ]);
  }
}

PfgRenderer.$inject = ['eventBus', 'bpmnRenderer'];

export default {
  __init__: ['pfgRenderer'],
  pfgRenderer: ['type', PfgRenderer]
};
