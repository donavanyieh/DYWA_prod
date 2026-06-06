## Group Buy Prototype Test Case Suite

Scope: These test cases are designed from the finalized ideal prototype in `app/main.py` and the proposed bug scenarios in `BUG_PROPOSALS.md`.

Usage: Expected results describe the correct behavior. When run against `app/buggy_main_seed.py`, failures on bug coverage cases should expose the intended injected bugs. When run after an autofix, the same cases should pass again.

Baseline reset: Before each independent test, reset in-memory data with `POST /admin/reset` unless the preconditions say to reuse state from earlier steps.

## Test Case ID: TC-001

| Field | Details |
| --- | --- |
| Title | Product listing displays available group-buy products |
| Priority | P1 |
| Type | Happy Path |
| Covers | Core product catalog |
| Preconditions | App is running; state has been reset. |
| Test Data | Any mock user, default `u001`. |
| Steps | 1. Open `/products` or `/`.<br>2. Review product cards.<br>3. Open `Wireless Earbuds` product details. |
| Expected Result | 1. Product listing loads without error.<br>2. Cards show product name, normal price, group-buy price, rating, sold count, and image.<br>3. Product detail page shows `Wireless Earbuds`, category `Audio`, normal price `$29.99`, group-buy price `$19.99`, and group size `3`. |
| Validation Method | UI |
| Notes | Core smoke test. Does not directly cover a proposed bug. |

## Test Case ID: TC-002

| Field | Details |
| --- | --- |
| Title | Normal purchase creates confirmed order with quantity-based total |
| Priority | P0 |
| Type | Happy Path |
| Covers | Normal checkout, order creation, quantity pricing |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u001`; product `p002` Mini Portable Fan; quantity `2`. |
| Steps | 1. Open `/products/p002`.<br>2. Click `Buy Now`.<br>3. Set quantity to `2`.<br>4. Click `Place Order`.<br>5. Inspect resulting order page or `GET /api/orders/{orderId}`. |
| Expected Result | 1. Checkout page uses purchase type `NORMAL`.<br>2. Payable amount is `$31.98`.<br>3. Order status is `CONFIRMED`.<br>4. API order has `quantity: 2`, `purchaseType: NORMAL`, `finalPrice: 31.98`, and no `groupBuyId`. |
| Validation Method | UI + API |
| Notes | Also helps detect quantity total regressions outside group-buy flow. |

## Test Case ID: TC-003

| Field | Details |
| --- | --- |
| Title | Group Buy button routes to checkout before session creation |
| Priority | P0 |
| Type | Regression / Bug Coverage |
| Covers | Bug 1: Group Buy Button Creates Session Before Checkout |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u001`; product `p001` Wireless Earbuds. |
| Steps | 1. Open `/products/p001`.<br>2. Click `Group Buy`.<br>3. Observe current URL and page content.<br>4. Before placing order, request `GET /api/group-buys/p001-u001`. |
| Expected Result | 1. User lands on `/checkout?productId=p001&purchaseType=GROUP_BUY&startGroupBuy=true`.<br>2. Checkout title is `Start Group Buy Checkout`.<br>3. No group-buy page is shown before order placement.<br>4. API request for `p001-u001` returns `404 Group buy not found` before checkout is submitted. |
| Validation Method | UI + API |
| Notes | Against the buggy prototype, this should fail if clicking `Group Buy` creates or opens the group-buy session immediately. |

## Test Case ID: TC-004

| Field | Details |
| --- | --- |
| Title | Starting group buy after checkout creates pending group and pending order |
| Priority | P0 |
| Type | Happy Path |
| Covers | Group-buy creation after checkout, creator participation, share link |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u001`; product `p001`; quantity `1`. |
| Steps | 1. Open `/products/p001`.<br>2. Click `Group Buy`.<br>3. Keep quantity `1` and click `Place Order`.<br>4. Open the created order and group-buy page.<br>5. Request `GET /api/group-buys/p001-u001`. |
| Expected Result | 1. Order is created with status `PENDING_GROUP_BUY`.<br>2. Order includes a link back to group buy `p001-u001`.<br>3. Group buy has creator `u001`, participant list `["u001"]`, participant count `1`, required group size `3`, and status `PENDING`.<br>4. Share URL points to `/group-buy/p001-u001`. |
| Validation Method | UI + API |
| Notes | Core group-buy start flow. Supports Bug 1 validation by confirming creation happens only after checkout. |

## Test Case ID: TC-005

| Field | Details |
| --- | --- |
| Title | Quantity greater than one still counts creator as one participant |
| Priority | P0 |
| Type | Regression / Bug Coverage |
| Covers | Bug 2: Participant Count Uses Quantity Instead of Unique Users |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u001`; product `p001` requiring `3`; quantity `3`. |
| Steps | 1. Start group buy checkout for `/products/p001` as `u001`.<br>2. Set quantity to `3`.<br>3. Place order.<br>4. Request `GET /api/group-buys/p001-u001`. |
| Expected Result | 1. Creator order is accepted with `quantity: 3` and `finalPrice: 59.97`.<br>2. Group-buy participant count is `1`, not `3`.<br>3. Participant list contains only `u001`.<br>4. Group-buy status remains `PENDING`. |
| Validation Method | UI + API |
| Notes | Against the buggy prototype, participant count may become `3` and status may incorrectly become `READY_TO_CHECKOUT`. |

## Test Case ID: TC-006

| Field | Details |
| --- | --- |
| Title | Non-creator joins group buy through checkout |
| Priority | P0 |
| Type | Happy Path |
| Covers | Join flow, participant update, checkout-required behavior |
| Preconditions | Group buy `p001-u001` exists with only creator `u001`. |
| Test Data | User `u002`; product `p001`; group buy `p001-u001`; quantity `1`. |
| Steps | 1. Switch mock user to `u002`.<br>2. Open `/group-buy/p001-u001`.<br>3. Click `Join Group Buy`.<br>4. Complete checkout with quantity `1`.<br>5. Request `GET /api/group-buys/p001-u001`. |
| Expected Result | 1. `u002` is taken to group-buy checkout for `p001-u001`.<br>2. Order status is `PENDING_GROUP_BUY`.<br>3. Participant list becomes `["u001", "u002"]`.<br>4. Participant count is `2` and status remains `PENDING` because `p001` requires `3` users. |
| Validation Method | UI + API |
| Notes | Core join behavior. Also supports Bug 2 by confirming unique-user participant counting. |

## Test Case ID: TC-007

| Field | Details |
| --- | --- |
| Title | Group buy becomes ready only after required unique users join |
| Priority | P0 |
| Type | Happy Path / Regression |
| Covers | Status progression from `PENDING` to `READY_TO_CHECKOUT`; Bug 2 |
| Preconditions | Group buy `p001-u001` has participants `u001` and `u002`. |
| Test Data | User `u003`; product `p001`; quantity `1`. |
| Steps | 1. Switch mock user to `u003`.<br>2. Open `/group-buy/p001-u001`.<br>3. Join through checkout.<br>4. Return to `/group-buy/p001-u001`.<br>5. Request `GET /api/group-buys/p001-u001`. |
| Expected Result | 1. `u003` order is `PENDING_GROUP_BUY`.<br>2. Participant list contains exactly `u001`, `u002`, and `u003`.<br>3. Participant count is `3`.<br>4. Status becomes `READY_TO_CHECKOUT`. |
| Validation Method | UI + API |
| Notes | Confirms readiness depends on unique participants, not quantities. |

## Test Case ID: TC-008

| Field | Details |
| --- | --- |
| Title | Same user cannot join same group buy twice |
| Priority | P1 |
| Type | Negative |
| Covers | Duplicate participant prevention |
| Preconditions | Group buy `p001-u001` already includes participant `u002`. |
| Test Data | User `u002`; group buy `p001-u001`; product `p001`. |
| Steps | 1. Switch mock user to `u002`.<br>2. Open `/group-buy/p001-u001`.<br>3. Attempt to join again from UI, if possible.<br>4. Send API request `POST /api/orders` with `userId: u002`, `productId: p001`, `purchaseType: GROUP_BUY`, `groupBuyId: p001-u001`, `quantity: 1`. |
| Expected Result | 1. UI disables or prevents the join action for an existing participant.<br>2. API returns `400 USER_ALREADY_JOINED_GROUP_BUY`.<br>3. Participant list and order list do not gain duplicate `u002` entries. |
| Validation Method | UI + API |
| Notes | Core negative case. |

## Test Case ID: TC-009

| Field | Details |
| --- | --- |
| Title | Same creator cannot start duplicate active group buy for same product |
| Priority | P0 |
| Type | Regression |
| Covers | Active same-product same-creator guard |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u001`; product `p002`; quantity `1`. |
| Steps | 1. As `u001`, start a group buy for `p002` and place order.<br>2. As `u001`, open `/products/p002` again.<br>3. Click `Group Buy` and place order again, or call `POST /api/orders` with `startGroupBuy: true` for the same user/product.<br>4. Inspect the response and `GET /api/group-buys/p002-u001`. |
| Expected Result | 1. The second start attempt does not create a new active session.<br>2. Response returns or redirects to existing group buy `p002-u001`.<br>3. There is still one active group-buy session for product `p002` and creator `u001`.<br>4. Existing session status remains non-`SUCCESS` until finalized. |
| Validation Method | UI + API |
| Notes | Covers the active-session rule requested after the ideal prototype update. |

## Test Case ID: TC-010

| Field | Details |
| --- | --- |
| Title | Creator may start new same-product group buy after previous one succeeds |
| Priority | P1 |
| Type | Edge Case / Regression |
| Covers | Active-session lifecycle after `SUCCESS` |
| Preconditions | App is running; state has been reset. |
| Test Data | Product `p002` requiring `2`; creator `u001`; joiner `u002`. |
| Steps | 1. As `u001`, start group buy `p002-u001`.<br>2. As `u002`, join it so status becomes `READY_TO_CHECKOUT`.<br>3. As `u001`, finalize the group buy.<br>4. As `u001`, start another group buy for `p002` through checkout.<br>5. Inspect response and group-buy page. |
| Expected Result | 1. First group reaches `SUCCESS` and its orders become `CONFIRMED`.<br>2. A new start attempt after success is allowed by business rule.<br>3. The new session is available for checkout flow and does not incorrectly return the old successful session as active. |
| Validation Method | UI + API |
| Notes | The current deterministic ID design may reuse `p002-u001`; validate behavior according to intended lifecycle rule. This is a strong candidate for clarifying product requirements if implementation cannot create a distinct historical session. |

## Test Case ID: TC-011

| Field | Details |
| --- | --- |
| Title | Group-buy checkout shows original unit price and discount |
| Priority | P0 |
| Type | Regression / Bug Coverage |
| Covers | Bug 4: Group-Buy Checkout Shows Discounted Price as Unit Price |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u001`; product `p001`; normal price `$29.99`; group-buy price `$19.99`; quantity `1`. |
| Steps | 1. Open `/products/p001`.<br>2. Click `Group Buy`.<br>3. Inspect checkout order summary before placing order. |
| Expected Result | 1. Checkout shows purchase type `GROUP_BUY`.<br>2. Unit/original price displays `$29.99`.<br>3. Discount displays `$10.00`.<br>4. Payable displays `$19.99`. |
| Validation Method | UI |
| Notes | Against the buggy prototype, unit/original price may incorrectly display `$19.99`. |

## Test Case ID: TC-012

| Field | Details |
| --- | --- |
| Title | Group-buy checkout total recalculates when quantity changes |
| Priority | P0 |
| Type | Regression / Bug Coverage |
| Covers | Bug 3: Checkout Final Total Ignores Quantity |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u001`; product `p001`; quantity `3`; normal price `$29.99`; group-buy price `$19.99`. |
| Steps | 1. Open group-buy checkout for `p001` as `u001`.<br>2. Change quantity from `1` to `3`.<br>3. Inspect checkout summary.<br>4. Place order and inspect the API order response. |
| Expected Result | 1. Discount updates to `$30.00`.<br>2. Payable updates to `$59.97`.<br>3. Created order has `quantity: 3`, `discountAmount: 30.0`, and `finalPrice: 59.97`. |
| Validation Method | UI + API |
| Notes | Against the buggy prototype, UI and/or backend may keep payable at single-unit `$19.99`. |

## Test Case ID: TC-013

| Field | Details |
| --- | --- |
| Title | Normal checkout total recalculates when quantity changes |
| Priority | P1 |
| Type | Regression |
| Covers | Quantity pricing for non-group orders |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u003`; product `p005`; normal price `$12.00`; quantity `4`. |
| Steps | 1. Open `/products/p005`.<br>2. Click `Buy Now`.<br>3. Change quantity to `4`.<br>4. Place order.<br>5. Inspect order page or API response. |
| Expected Result | 1. Checkout payable shows `$48.00`.<br>2. Order status is `CONFIRMED`.<br>3. API order has `quantity: 4`, `discountAmount: 0.0`, and `finalPrice: 48.0`. |
| Validation Method | UI + API |
| Notes | Complements Bug 3 coverage outside group-buy pricing. |

## Test Case ID: TC-014

| Field | Details |
| --- | --- |
| Title | Checkout rejects zero, negative, and alphabetic quantity values |
| Priority | P0 |
| Type | Negative / Bug Coverage |
| Covers | Bug 5: Checkout Quantity Accepts Zero Or Negative Values |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u001`; product `p001`; invalid quantities `0`, `-1`, `abc`, empty string. |
| Steps | 1. Open group-buy checkout for `p001`.<br>2. Enter each invalid quantity value.<br>3. Observe UI behavior and attempt `Place Order`.<br>4. Send API `POST /api/orders` with each invalid `quantity`. |
| Expected Result | 1. UI sanitizes or rejects invalid input and does not allow an order using invalid quantity.<br>2. Payable never becomes zero, negative, `NaN`, or blank.<br>3. API rejects invalid values with validation error instead of creating an order.<br>4. No order or group-buy participant is created from invalid values. |
| Validation Method | UI + API |
| Notes | Against the buggy prototype, invalid quantities may create negative totals or invalid orders. |

## Test Case ID: TC-015

| Field | Details |
| --- | --- |
| Title | Quantity boundary accepts 1 and 9 but rejects values above maximum |
| Priority | P2 |
| Type | Edge Case |
| Covers | Quantity validation boundaries |
| Preconditions | App is running; state has been reset. |
| Test Data | Product `p003`; user `u004`; quantities `1`, `9`, `10`. |
| Steps | 1. Submit a normal order with quantity `1`.<br>2. Reset state and submit a normal order with quantity `9`.<br>3. Reset state and submit API order with quantity `10`. |
| Expected Result | 1. Quantity `1` is accepted and final price is `$9.99`.<br>2. Quantity `9` is accepted and final price is `$89.91`.<br>3. Quantity `10` is rejected by API validation and no order is created. |
| Validation Method | API |
| Notes | Current data model uses `quantity` range `1..9`. |

## Test Case ID: TC-016

| Field | Details |
| --- | --- |
| Title | Non-creator cannot see or use finalize action |
| Priority | P0 |
| Type | Negative / Bug Coverage |
| Covers | Bug 6: Non-Creator Can Finalize Group Buy |
| Preconditions | App is running; state has been reset. |
| Test Data | Product `p002` requiring `2`; creator `u001`; joiner `u002`. |
| Steps | 1. As `u001`, start group buy `p002-u001`.<br>2. As `u002`, join it so status becomes `READY_TO_CHECKOUT`.<br>3. Stay logged in as `u002` and open `/group-buy/p002-u001`.<br>4. Inspect available buttons.<br>5. Send `POST /api/group-buys/p002-u001/finalize` with `userId: u002`. |
| Expected Result | 1. Group status is `READY_TO_CHECKOUT`.<br>2. `Finalize Group Buy` button is not visible to `u002`.<br>3. API returns `400 ONLY_CREATOR_CAN_FINALIZE`.<br>4. Group status remains `READY_TO_CHECKOUT`.<br>5. Pending orders remain `PENDING_GROUP_BUY`. |
| Validation Method | UI + API |
| Notes | Against the buggy prototype, the button may be visible or the API may allow finalization by `u002`. |

## Test Case ID: TC-017

| Field | Details |
| --- | --- |
| Title | Creator finalizes ready group buy successfully |
| Priority | P0 |
| Type | Happy Path |
| Covers | Creator-only finalization and order confirmation |
| Preconditions | Group buy `p002-u001` exists with participants `u001` and `u002`; status is `READY_TO_CHECKOUT`. |
| Test Data | Creator `u001`; product `p002`. |
| Steps | 1. Switch mock user to `u001`.<br>2. Open `/group-buy/p002-u001`.<br>3. Click `Finalize Group Buy`.<br>4. Inspect group buy and all related orders. |
| Expected Result | 1. Finalize button is visible to creator `u001`.<br>2. Group status changes to `SUCCESS`.<br>3. Orders in `p002-u001` change from `PENDING_GROUP_BUY` to `CONFIRMED`.<br>4. Join button is disabled after success. |
| Validation Method | UI + API |
| Notes | Complements Bug 6 by proving the creator path still works. |

## Test Case ID: TC-018

| Field | Details |
| --- | --- |
| Title | Creator cannot finalize before group reaches required size |
| Priority | P1 |
| Type | Negative |
| Covers | Finalization readiness validation |
| Preconditions | App is running; state has been reset. |
| Test Data | Product `p001` requiring `3`; creator `u001` only. |
| Steps | 1. As `u001`, start group buy `p001-u001` with quantity `1`.<br>2. Open `/group-buy/p001-u001`.<br>3. Inspect visible actions.<br>4. Send `POST /api/group-buys/p001-u001/finalize` with `userId: u001`. |
| Expected Result | 1. Group status is `PENDING`.<br>2. Finalize button is not visible.<br>3. API returns `400 GROUP_BUY_SIZE_NOT_REACHED`.<br>4. Group status remains `PENDING` and creator order remains `PENDING_GROUP_BUY`. |
| Validation Method | UI + API |
| Notes | Guards against bypassing readiness checks. |

## Test Case ID: TC-019

| Field | Details |
| --- | --- |
| Title | Finalizing one group buy confirms only orders from that exact group |
| Priority | P0 |
| Type | Regression / Bug Coverage |
| Covers | Bug 7: Finalize Confirms Orders For Same Product Instead Of Same Group Buy |
| Preconditions | App is running; state has been reset. |
| Test Data | Product `p001`; group A creator `u001`; group B creator `u002`; additional joiners `u003`, `u004`. |
| Steps | 1. As `u001`, start group A for `p001`; record creator order ID.<br>2. As `u002`, start separate group B for `p001`; record creator order ID.<br>3. Add `u003` and `u004` to group A so group A becomes `READY_TO_CHECKOUT`.<br>4. Do not add enough participants to group B.<br>5. As `u001`, finalize group A.<br>6. Inspect all recorded orders and both group-buy statuses. |
| Expected Result | 1. Group A becomes `SUCCESS`.<br>2. Only group A orders are `CONFIRMED`.<br>3. Group B remains `PENDING`.<br>4. Group B creator order remains `PENDING_GROUP_BUY`.<br>5. No order from group B is confirmed by finalizing group A. |
| Validation Method | API |
| Notes | Against the buggy prototype, group B orders for the same product may incorrectly become `CONFIRMED`. |

## Test Case ID: TC-020

| Field | Details |
| --- | --- |
| Title | Joining finalized group buy is blocked |
| Priority | P1 |
| Type | Negative / Regression |
| Covers | Post-success join prevention |
| Preconditions | Group buy `p002-u001` is `SUCCESS`. |
| Test Data | User `u003`; product `p002`; group buy `p002-u001`. |
| Steps | 1. Switch to `u003` and open `/group-buy/p002-u001`.<br>2. Inspect join button.<br>3. Send `POST /api/orders` with `userId: u003`, `productId: p002`, `purchaseType: GROUP_BUY`, `groupBuyId: p002-u001`, `quantity: 1`. |
| Expected Result | 1. Join button is disabled on UI.<br>2. API returns `400 GROUP_BUY_ALREADY_SUCCESS`.<br>3. No new order is created.<br>4. Participant list remains unchanged. |
| Validation Method | UI + API |
| Notes | Core lifecycle guard after finalization. |

## Test Case ID: TC-021

| Field | Details |
| --- | --- |
| Title | Group-buy checkout rejects mismatched product and group-buy ID |
| Priority | P1 |
| Type | Negative |
| Covers | Data integrity for group-buy checkout |
| Preconditions | App is running; state has been reset; group buy `p001-u001` exists. |
| Test Data | User `u002`; request product `p002`; groupBuyId `p001-u001`. |
| Steps | 1. Create group buy `p001-u001` as `u001`.<br>2. Send `POST /api/orders` with `userId: u002`, `productId: p002`, `purchaseType: GROUP_BUY`, `groupBuyId: p001-u001`, `quantity: 1`. |
| Expected Result | 1. API returns `400 GROUP_BUY_PRODUCT_MISMATCH`.<br>2. No order is created for `u002`.<br>3. Group buy `p001-u001` participants remain unchanged. |
| Validation Method | API |
| Notes | Prevents joining a group with an unrelated product checkout. |

## Test Case ID: TC-022

| Field | Details |
| --- | --- |
| Title | Missing group-buy ID is rejected for group-buy checkout |
| Priority | P1 |
| Type | Negative |
| Covers | Required group-buy checkout data |
| Preconditions | App is running; state has been reset. |
| Test Data | User `u001`; product `p004`; purchase type `GROUP_BUY`; `startGroupBuy: false`; no `groupBuyId`. |
| Steps | 1. Send `POST /api/orders` with `userId: u001`, `productId: p004`, `purchaseType: GROUP_BUY`, `quantity: 1`, no `groupBuyId`, and no `startGroupBuy`.<br>2. Inspect response and state. |
| Expected Result | 1. API returns `400 GROUP_BUY_CHECKOUT_REQUIRES_GROUP_BUY_ID`.<br>2. No order is created.<br>3. No group-buy session is created. |
| Validation Method | API |
| Notes | Core data validation. |
