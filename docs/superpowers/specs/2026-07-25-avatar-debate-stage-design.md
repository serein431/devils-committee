# Avatar Debate Stage Design

## Goal

Turn the first screen into a character-led debate. Four large 3D heads should be the first thing visitors see; the existing research, audit, metrics, and disagreement interface begins below the first viewport.

## Stage

The stage fills at least one viewport below the top bar. BULL, BEAR, MACRO, and RISK begin as four equally prominent floating heads. When a claim arrives, that speaker moves to the center, grows to roughly 1.3 times the default size, and uses the speaking image. The other three remain in their original areas, shrink, move behind the speaker, and drop to about 28% opacity.

The active speaker shows a short excerpt beside the head. Claims are placed in a display queue so rapid server events still produce readable turns of about two seconds each. When the queue ends, all four heads return to equal size and the stage points visitors to the evidence below.

## Existing Interface

The current title, command explanation, agent cards, audit console, disagreement view, boundaries, and trace remain intact in a `details` section after the stage. Agent cards return to their compact text-first layout; avatars appear only in the stage.

## Responsive and Motion

Desktop uses an overlapping theater composition. Mobile uses a compact two-row layout while keeping the active head centered. `prefers-reduced-motion` removes movement but preserves the active speaker through size, opacity, and labels.

## Verification

DOM tests check four stage heads, active-speaker state, speaking image selection, details ordering, safe text rendering, and the renamed `未达成一致` status. A browser run checks desktop and mobile screenshots plus the console.
