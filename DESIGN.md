# Sequitor desktop experience

## Direction

An investigative viewing room: a quiet dark field resolves into a growing public conversation. The sole authored moment is the transition from an ambient field of decorative public-post fragments to a real anchored conversation. The viewer carries the product; controls and prose recede.

## Surface and layout

- One route and one desktop composition; no view tabs.
- Landing state: 100vh with wordmark, heading, one search field, and Dario example control.
- Explore state: 70% of usable width for Conversation Space, 30% for a 360px reading column.
- A 72px compact header remains after search begins.
- The activity strip is 88px high below the viewer. It has Hour, Day, Month and one compact playback control.
- The reading column contains only compact context, selected starting post, observed lineage, then related posts.
- Outer spacing: 48px desktop, reducing to 32px at 1100px. Scene border radius: 14px. Controls: 8px.

## Type and color

- Inter remains the UI face. Use 56px/0.98/570 for landing heading, 20px/1.2/600 for selected-post author/title, 13px/1.6 for post text, and 11px/1.4 for secondary labels.
- Background `#080d11`; surface `#0d141a`; elevated reading surface `#101922`; line `#253542`.
- Primary text `#e8eff4`; muted text `#9baebb`; dim text `#718695`; accent `#8bd5f1`; positive collection state `#78d7b2`.
- Accent is reserved for focus, active controls, the reference node, and observed relationship selection. No gradients as text or decorative glass effects.

## Motion thesis

The focal sequence is **ambient public speech collapsing into a specific conversation**. Decorative floating cards use Three.js canvas textures and disappear as meaningful run milestones arrive. A 160–220ms quiet void precedes the anchor's 380ms arrival. First real posts appear one at a time, then the reveal queue accelerates as its backlog grows. Their graph-node and reading-card births share a timestamp.

- Routine controls: 140–180ms.
- Search field/header continuity: 260ms.
- Anchor and camera movement: 380–650ms ease-out.
- No infinite animation after collection settles, except subtle state indication during active collection.
- Any deliberate drag/zoom stops automatic camera movement at once.
- Reduced motion removes drifting and camera travel, uses immediate/fade state transitions, and preserves the same data order.

## Viewer behavior

- Reference starts at the spatial origin.
- The scene grows through a camera envelope that only expands while automatic mode is active; it never repeatedly re-fits or zooms inward between batches.
- Stable coordinates remain stable. A provisional coordinate can transition once to its resolved coordinate.
- Default edges show selected post lineage only. A small toggle can hide them or reveal observed links. Edges terminate before node surfaces.
- User selection synchronizes the node, reading card, and edge highlight. Selection does not move the camera; Focus is explicit.

## Interaction states

- `landing`: ready input and Dario example.
- `searching`: backend active, decorative field visible, Stop and Skip available.
- `anchoring`: seed known; intro clears and reference appears.
- `assembling`: received posts pass through a single reveal scheduler; user can interact.
- `exploring`: queue drained; minimal controls visible.
- `partial` / `error`: retain received evidence and show a short recovery action.

## Accessibility and performance

- Keyboard-accessible input, controls, cards, and scene fallbacks; visible focus ring uses accent.
- Reading column stays useful without WebGL.
- Keep only 24–40 decorative cards in the opening scene. Dispose their textures and geometry on handoff.
- Node geometry is instanced; do not drive React state at animation-frame frequency.
- Desktop scope only for this build. Do not add mobile behavior as part of the Dario deliverable.

## Demo acceptance

- Dario begins at a clean landing state and reaches a single viewer-plus-reading-column state.
- Decorative cards are never presented as search results.
- The reference appears before every result is displayed.
- Every Dario result is revealed through the same queue; completion does not jump the graph to a larger corpus.
- No technical/model text appears in the main interface.
