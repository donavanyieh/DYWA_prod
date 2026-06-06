# Shopping App Expected Behavior

Persona agents should flag inconsistencies that a real customer could observe from the application itself.

Examples of expected behavior:

- Product information should remain internally consistent between product listings, cart, and checkout.
- Item quantities, line-item subtotals, cart totals, and charged order totals should agree with each other.
- Actions should have visible effects that match their labels.
- Checkout should not silently lose or alter cart state.
- Errors should be understandable and related to the user action that caused them.

This file describes general behavior principles. It must not name planted bugs or prescribe specific bug reports.

