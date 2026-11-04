# Test fixtures

These are **small, hand-constructed payloads in the exact schema of each API**
(npm range, pypistats overall, Algolia HN search/items, SEC companyfacts,
GitHub Link headers). They exist only to unit-test parsing and edge cases
(deleted comments, restated SEC values, Q4 derivation, false-positive mentions).
They are not real observations and are never written to `data/`.
