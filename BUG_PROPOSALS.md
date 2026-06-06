## Bug 1: Group Buy Button Creates Session Before Checkout

Area: Frontend

Feature affected:
Product Detail Page -> Group Buy entry flow

Bug behavior:
Clicking `Group Buy` calls `POST /api/group-buys` or navigates directly to `/group-buy/...` instead of going to checkout first.

Expected correct behavior:
Clicking `Group Buy` should navigate to checkout with `purchaseType=GROUP_BUY&startGroupBuy=true`. The group-buy session/link should only be created after placing the order.

Why this is a good autofix demo bug:
It is immediately visible in the UI, directly tied to the main flow, and has a clear expected route. The fix is localized to the product-detail click handler.

Suggested reproduction steps:
1. Open `/products`.
2. Open a product detail page.
3. Click `Group Buy`.
4. Observe that the app does not land on checkout first.

Suggested validation after fix:
1. Click `Group Buy`.
2. Confirm URL is `/checkout?productId=...&purchaseType=GROUP_BUY&startGroupBuy=true`.
3. Confirm no group-buy page/link exists until `Place Order`.


## Bug 2: Participant Count Uses Quantity Instead of Unique Users

Area: Backend

Feature affected:
Group-buy participant counting and status progression

Bug behavior:
When a user places a group-buy order with quantity greater than 1, the participant count increases by quantity instead of counting the user once.

Expected correct behavior:
Each unique user should count as one participant per group-buy session, regardless of quantity purchased.

Why this is a good autofix demo bug:
It is a classic business-logic mistake, easy to reproduce via API or UI quantity input, and directly affects `PENDING` vs `READY_TO_CHECKOUT`.

Suggested reproduction steps:
1. Start a group buy for a product requiring 3 participants.
2. Place the creator order with quantity `3`.
3. Open the group-buy page.
4. Observe participant count becomes `3` or status becomes `READY_TO_CHECKOUT`.

Suggested validation after fix:
1. Repeat with quantity `3`.
2. Confirm participant count is `1`.
3. Confirm status remains `PENDING` until enough unique users join.


## Bug 3: Checkout Final Total Ignores Quantity

Area: Frontend / Backend

Feature affected:
Checkout price summary

Bug behavior:
When the user changes quantity, the checkout page still calculates final payable using a single unit.

Example:
- Product normal price: `$29.99`
- Group-buy price: `$19.99`
- Quantity: `3`

Incorrect checkout display:
- Original unit price: `$29.99`
- Discount: `-$10.00`
- Final payable: `$19.99`

Expected correct behavior:
- Original unit price: `$29.99`
- Discount: `-$30.00`
- Final payable: `$59.97`

Why this is useful:
Very easy to discover by changing quantity, and easy to verify after fixing.


## Bug 4: Group-Buy Checkout Shows Discounted Price as Unit Price

Area: Frontend

Feature affected:
Checkout page order summary

Bug behavior:
For group-buy checkout, the order summary shows `unitPrice` as the discounted group-buy price instead of the original product price.

Expected correct behavior:
The checkout summary should show original unit price, discount amount, and discounted final payable amount.

Why this is a good autofix demo bug:
It is easy to see on the checkout page, easy to verify with one product, and exercises pricing understanding without breaking the flow.

Suggested reproduction steps:
1. Open a product with normal price `$29.99` and group-buy price `$19.99`.
2. Click `Group Buy`.
3. On checkout, inspect the order summary.
4. Observe original unit price incorrectly shows `$19.99`.

Suggested validation after fix:
1. Open the same group-buy checkout.
2. Confirm original unit price is `$29.99`.
3. Confirm discount is `-$10.00`.
4. Confirm final payable is `$19.99`.


## Bug 5: Checkout Quantity Accepts Zero Or Negative Values

Area: Frontend / Backend

Feature affected:
Checkout quantity input and order creation

Bug behavior:
The checkout quantity field allows `0`, `-1`, or other invalid values, and the UI/backend uses that value to calculate totals or create orders.

Example:
- User enters quantity `-2`
- Checkout may show a negative payable amount or negative discount
- Backend may create an order with invalid quantity

Expected correct behavior:
Quantity should be clamped or rejected so it is always at least `1`.

Why this is useful:
It is a common boundary-input bug, simple to reproduce, and can be verified through both UI and API response.


## Bug 6: Non-Creator Can Finalize Group Buy

Area: Backend

Feature affected:
Creator-only finalization

Bug behavior:
Any participant can call the finalize endpoint once the group reaches required size, even if they are not the creator.

Expected correct behavior:
Only `creatorUserId` can finalize. Non-creators should receive `ONLY_CREATOR_CAN_FINALIZE`.

Why this is a good autofix demo bug:
It is highly relevant to permissions, easy to test with two mock users, and can be validated through the API and UI behavior.

Suggested reproduction steps:
1. User `u001` starts a group buy.
2. Other users join until status is `READY_TO_CHECKOUT`.
3. Call `POST /api/group-buys/{id}/finalize` as `u002`.
4. Observe the group becomes `SUCCESS`.

Suggested validation after fix:
1. Repeat the same request as `u002`.
2. Confirm API returns an error.
3. Confirm group status remains `READY_TO_CHECKOUT`.
4. Finalize as `u001` and confirm success.


## Bug 7: Finalize Confirms Orders For Same Product Instead Of Same Group Buy

Area: Backend

Feature affected:
Creator finalization and order status updates

Bug behavior:
When the creator finalizes one group buy, the backend confirms all pending group-buy orders for the same product, including orders from other group-buy sessions started by other creators.

Expected correct behavior:
Only orders whose `groupBuyId` matches the finalized group-buy session should be marked `CONFIRMED`.

Why this is a good autofix demo bug:
One agent can reproduce it by switching mock users. It is a realistic data-scoping bug and requires checking order details after finalization.

Suggested reproduction steps:
1. As `u001`, start group buy for `p001`.
2. As `u002`, start a separate group buy for `p001`.
3. Add enough participants only to `p001-u001` so it becomes `READY_TO_CHECKOUT`.
4. Finalize `p001-u001` as `u001`.
5. Inspect order status for `p001-u002`.
6. Observe unrelated orders were marked `CONFIRMED`.

Suggested validation after fix:
1. Repeat the setup.
2. Finalize `p001-u001`.
3. Confirm only `p001-u001` orders become `CONFIRMED`.
4. Confirm `p001-u002` orders remain `PENDING_GROUP_BUY`.
