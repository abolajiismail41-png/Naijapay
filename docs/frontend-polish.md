# Phase 14 — Frontend Polish

This phase improves the existing React/Vite interface without changing financial APIs or transaction behavior.

## Included

- Responsive service tiles that collapse to a single-column touch-friendly list on narrow screens and a two-column grid on larger screens.
- Keyboard-accessible skip-to-content link and focus management after route changes.
- Consistent hover, active, focus-visible, and disabled states.
- Better handling of narrow viewports, long content, horizontal data tables, and safe-area insets.
- Reduced-motion support for added transitions and predictable navigation scrolling.
- Subtle wallet-card depth treatment that respects existing theme tokens.

## Scope and compatibility

- Existing routes, API contracts, authentication, wallet ledger, payment providers, and transaction state logic are unchanged.
- No new runtime dependency or database migration is required.
- The interface continues to use the existing light/dark design tokens and respects `prefers-reduced-motion`.

## Validation

Run from the project root:

```bash
docker compose run --rm frontend npm run typecheck
docker compose run --rm frontend npm test
docker compose run --rm frontend npm run build
```

A production build should be completed before deploying. Device testing should cover 320px mobile width, iOS safe-area insets, keyboard-only navigation, reduced motion, and desktop admin tables.
