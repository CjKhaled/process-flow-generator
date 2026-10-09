/**
 * The palette, cut down to what this project's diagrams are made of.
 *
 * bpmn-js offers fifteen entries covering the whole of BPMN. A process flow here
 * is built from five things -- a start, an end, a step, a decision and a
 * handed-off subprocess -- plus notes. Offering data stores and pools invites
 * someone to add an element no later stage understands.
 *
 * The tools are all kept. Hand, lasso, space and connect are ways of working
 * with what is on the canvas rather than ways of putting new things on it, and
 * none of them can produce an element this project cannot draw.
 *
 * Registered below the default provider's priority so it runs *after* it: this
 * returns an updater, which diagram-js hands the entries collected so far, and
 * there is nothing to remove until the defaults are in.
 */

/** Below the 1000 the stock provider registers at, so its entries exist to edit. */
const PRIORITY = 500;

/**
 * Entries removed from the stock palette.
 *
 * Every one is an element that would reach `bpmn/semantics.py` as something it
 * has no mapping for. Note that a text annotation is *not* in this list because
 * it was never in the palette to begin with -- bpmn-js only offers one from the
 * context pad, so it is built below rather than kept.
 */
const REMOVED = [
  'create.intermediate-event',
  'create.data-object',
  'create.data-store',
  'create.group',
  'create.participant-expanded'
];

export class PfgPalette {
  constructor(palette, create, elementFactory, translate) {
    this.create = create;
    this.elementFactory = elementFactory;
    this.translate = translate;

    palette.registerProvider(PRIORITY, this);
  }

  getPaletteEntries() {
    const create = this.create;
    const elementFactory = this.elementFactory;
    const translate = this.translate;

    function startAnnotation(event) {
      create.start(event, elementFactory.createShape({ type: 'bpmn:TextAnnotation' }));
    }

    // An updater rather than a set of entries: returning entries would only add
    // to what the stock provider contributed, and the point here is to take
    // most of it away.
    return function (entries) {
      REMOVED.forEach(function (id) {
        delete entries[id];
      });

      entries['create.text-annotation'] = {
        group: 'artifact',
        className: 'bpmn-icon-text-annotation',
        title: translate('Create text annotation'),
        action: {
          dragstart: startAnnotation,
          click: startAnnotation
        }
      };

      return entries;
    };
  }
}

PfgPalette.$inject = ['palette', 'create', 'elementFactory', 'translate'];

export default {
  __init__: ['pfgPalette'],
  pfgPalette: ['type', PfgPalette]
};
