import importlib
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient


APP_MODULE = os.getenv("GROUP_BUY_APP_MODULE", "app.main")
app_module = importlib.import_module(APP_MODULE)
app = app_module.app
GROUP_BUYS = app_module.GROUP_BUYS
ORDERS = app_module.ORDERS

ALICE = "u001"
BOB = "u002"
CAROL = "u003"
DAVID = "u004"

P001 = "p001"
P002 = "p002"
P003 = "p003"
P004 = "p004"
P005 = "p005"


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        response = test_client.post("/admin/reset")
        assert response.status_code == 200
        yield test_client
        test_client.post("/admin/reset")


def assert_status(response: Any, expected_status: int) -> None:
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )


def money(value: float) -> float:
    return round(value, 2)


def get_product(client: TestClient, product_id: str) -> dict[str, Any]:
    response = client.get(f"/api/products/{product_id}")
    assert_status(response, 200)
    return response.json()


def get_group_buy(client: TestClient, group_buy_id: str) -> dict[str, Any]:
    response = client.get(f"/api/group-buys/{group_buy_id}")
    assert_status(response, 200)
    return response.json()


def get_order(client: TestClient, order_id: str) -> dict[str, Any]:
    response = client.get(f"/api/orders/{order_id}")
    assert_status(response, 200)
    return response.json()


def create_normal_order(
    client: TestClient,
    user_id: str,
    product_id: str,
    quantity: int = 1,
) -> dict[str, Any]:
    response = client.post(
        "/api/orders",
        json={
            "userId": user_id,
            "productId": product_id,
            "purchaseType": "NORMAL",
            "quantity": quantity,
        },
    )
    assert_status(response, 200)
    return response.json()


def start_group_buy_order(
    client: TestClient,
    user_id: str,
    product_id: str,
    quantity: int = 1,
) -> dict[str, Any]:
    response = client.post(
        "/api/orders",
        json={
            "userId": user_id,
            "productId": product_id,
            "purchaseType": "GROUP_BUY",
            "startGroupBuy": True,
            "quantity": quantity,
        },
    )
    assert_status(response, 200)
    return response.json()


def join_group_buy(
    client: TestClient,
    user_id: str,
    product_id: str,
    group_buy_id: str,
    quantity: int = 1,
) -> dict[str, Any]:
    response = client.post(
        "/api/orders",
        json={
            "userId": user_id,
            "productId": product_id,
            "purchaseType": "GROUP_BUY",
            "groupBuyId": group_buy_id,
            "quantity": quantity,
        },
    )
    assert_status(response, 200)
    return response.json()


def finalize_group_buy(
    client: TestClient,
    group_buy_id: str,
    user_id: str,
    expected_status: int = 200,
) -> Any:
    response = client.post(
        f"/api/group-buys/{group_buy_id}/finalize",
        json={"userId": user_id},
    )
    assert_status(response, expected_status)
    return response.json()


def test_product_catalog_detail_and_html_routes_are_available(client: TestClient) -> None:
    # Covers TC-001: Product listing and details.
    response = client.get("/api/products")
    assert_status(response, 200)
    products = response.json()

    assert len(products) >= 5
    product_ids = {product["id"] for product in products}
    assert {P001, P002, P003, P004, P005}.issubset(product_ids)
    for product in products:
        assert product["id"]
        assert product["name"]
        assert product["imageUrl"].startswith("data:image/")
        assert product["normalPrice"] > product["groupBuyPrice"] > 0
        assert product["requiredGroupSize"] >= 2

    earbuds = get_product(client, P001)
    assert earbuds["name"] == "Wireless Earbuds"
    assert earbuds["normalPrice"] == 29.99
    assert earbuds["groupBuyPrice"] == 19.99
    assert earbuds["requiredGroupSize"] == 3

    for route in ["/", "/products", "/products/p001", "/checkout", "/group-buy/demo"]:
        html = client.get(route)
        assert_status(html, 200)
        assert "BuyTogether" in html.text


def test_group_buy_button_uses_checkout_flow_before_session_creation(
    client: TestClient,
) -> None:
    # Covers TC-003 and Bug 1: Group Buy must route to checkout before creating a session.
    html = client.get("/products/p001").text

    assert "goCheckout('${product.id}', 'GROUP_BUY', '', true)" in html, (
        "Product detail Group Buy button should navigate to checkout with startGroupBuy=true"
    )
    assert "startGroupBuyBeforeCheckout" not in html, (
        "Frontend should not create a group-buy session before checkout is submitted"
    )

    missing_group = client.get(f"/api/group-buys/{P001}-{ALICE}")
    assert_status(missing_group, 404)

    premature_create = client.post(
        "/api/group-buys",
        json={"productId": P001, "userId": ALICE, "quantity": 1},
    )
    assert premature_create.status_code in {404, 405}, (
        "POST /api/group-buys should not be available as a pre-checkout creation path"
    )


def test_normal_checkout_uses_normal_price_and_quantity_total(
    client: TestClient,
) -> None:
    # Covers TC-002 and TC-013: Normal checkout pricing and confirmed order status.
    product = get_product(client, P002)
    order = create_normal_order(client, ALICE, P002, quantity=2)

    assert order["purchaseType"] == "NORMAL"
    assert order["status"] == "CONFIRMED"
    assert order["groupBuyId"] is None
    assert order["unitPrice"] == product["normalPrice"]
    assert order["quantity"] == 2
    assert order["discountAmount"] == 0.0
    assert order["finalPrice"] == money(product["normalPrice"] * 2)


def test_group_buy_start_creates_pending_order_link_and_unique_creator_count(
    client: TestClient,
) -> None:
    # Covers TC-004, TC-005, TC-012, Bug 2, and Bug 3.
    product = get_product(client, P001)
    order = start_group_buy_order(client, ALICE, P001, quantity=3)
    group_buy_id = f"{P001}-{ALICE}"
    group_buy = get_group_buy(client, group_buy_id)

    assert order["status"] == "PENDING_GROUP_BUY"
    assert order["purchaseType"] == "GROUP_BUY"
    assert order["groupBuyId"] == group_buy_id
    assert order["quantity"] == 3
    assert order["discountAmount"] == money(
        (product["normalPrice"] - product["groupBuyPrice"]) * 3
    ), "Group-buy discount should be multiplied by quantity"
    assert order["finalPrice"] == money(product["groupBuyPrice"] * 3), (
        "Group-buy final price should be discounted unit price times quantity"
    )

    assert group_buy["creatorUserId"] == ALICE
    assert group_buy["participants"] == [ALICE], (
        "Quantity 3 should still count the creator as only one unique participant"
    )
    assert group_buy["participantCount"] == 1
    assert group_buy["requiredGroupSize"] == 3
    assert group_buy["status"] == "PENDING"
    assert group_buy["shareUrl"].endswith(f"/group-buy/{group_buy_id}")
    assert order["id"] in group_buy["orderIds"]


def test_duplicate_active_creator_group_buy_reuses_existing_session(
    client: TestClient,
) -> None:
    # Covers TC-009: Same product + same creator cannot create duplicate active sessions.
    first = start_group_buy_order(client, ALICE, P002)
    response = client.post(
        "/api/orders",
        json={
            "userId": ALICE,
            "productId": P002,
            "purchaseType": "GROUP_BUY",
            "startGroupBuy": True,
            "quantity": 1,
        },
    )
    assert_status(response, 200)
    second = response.json()

    assert second["existingGroupBuy"] is True
    assert second["groupBuy"]["id"] == first["groupBuyId"]
    assert second["groupBuy"]["status"] != "SUCCESS"
    assert len(GROUP_BUYS) == 1
    assert len(ORDERS) == 1


def test_different_creators_can_start_separate_group_buys_for_same_product(
    client: TestClient,
) -> None:
    # Covers TC-019 setup and multi-creator same-product behavior.
    alice_order = start_group_buy_order(client, ALICE, P001)
    bob_order = start_group_buy_order(client, BOB, P001)

    assert alice_order["groupBuyId"] == f"{P001}-{ALICE}"
    assert bob_order["groupBuyId"] == f"{P001}-{BOB}"
    assert len(GROUP_BUYS) == 2
    assert get_group_buy(client, alice_order["groupBuyId"])["creatorUserId"] == ALICE
    assert get_group_buy(client, bob_order["groupBuyId"])["creatorUserId"] == BOB


def test_join_group_buy_flow_uses_unique_users_and_reaches_ready_state(
    client: TestClient,
) -> None:
    # Covers TC-006, TC-007, Bug 2, and stale status consistency.
    creator_order = start_group_buy_order(client, ALICE, P002)
    group_buy_id = creator_order["groupBuyId"]

    join_check = client.post(f"/api/group-buys/{group_buy_id}/join", json={"userId": BOB})
    assert_status(join_check, 200)
    assert join_check.json()["status"] == "checkout_required"
    assert f"groupBuyId={group_buy_id}" in join_check.json()["checkoutPath"]

    join_order = join_group_buy(client, BOB, P002, group_buy_id, quantity=2)
    group_buy = get_group_buy(client, group_buy_id)
    refreshed_creator_order = get_order(client, creator_order["id"])

    assert join_order["status"] == "PENDING_GROUP_BUY"
    assert join_order["quantity"] == 2
    assert group_buy["participants"] == [ALICE, BOB]
    assert group_buy["participantCount"] == 2
    assert group_buy["status"] == "READY_TO_CHECKOUT"
    assert refreshed_creator_order["groupBuy"]["status"] == "READY_TO_CHECKOUT", (
        "Order detail should reflect the current backend group-buy status"
    )


def test_same_user_cannot_join_group_buy_twice(client: TestClient) -> None:
    # Covers TC-008: Duplicate participant prevention.
    creator_order = start_group_buy_order(client, ALICE, P002)
    group_buy_id = creator_order["groupBuyId"]
    join_group_buy(client, BOB, P002, group_buy_id)

    duplicate_join_api = client.post(f"/api/group-buys/{group_buy_id}/join", json={"userId": BOB})
    duplicate_order = client.post(
        "/api/orders",
        json={
            "userId": BOB,
            "productId": P002,
            "purchaseType": "GROUP_BUY",
            "groupBuyId": group_buy_id,
            "quantity": 1,
        },
    )

    assert_status(duplicate_join_api, 400)
    assert duplicate_join_api.json()["detail"] == "USER_ALREADY_JOINED_GROUP_BUY"
    assert_status(duplicate_order, 400)
    assert duplicate_order.json()["detail"] == "USER_ALREADY_JOINED_GROUP_BUY"
    assert get_group_buy(client, group_buy_id)["participants"] == [ALICE, BOB]


def test_checkout_rejects_invalid_and_out_of_range_quantities(
    client: TestClient,
) -> None:
    # Covers TC-014, TC-015, and Bug 5.
    base_payload = {
        "userId": ALICE,
        "productId": P003,
        "purchaseType": "NORMAL",
    }

    for invalid_quantity in [0, -1, "abc", "", 10]:
        response = client.post(
            "/api/orders",
            json={**base_payload, "quantity": invalid_quantity},
        )
        assert_status(response, 422)

    quantity_one = create_normal_order(client, DAVID, P003, quantity=1)
    assert quantity_one["finalPrice"] == 9.99

    quantity_nine = create_normal_order(client, CAROL, P003, quantity=9)
    assert quantity_nine["finalPrice"] == 89.91


def test_group_buy_checkout_summary_displays_original_unit_price_source(
    client: TestClient,
) -> None:
    # Covers TC-011 and Bug 4: Group-buy checkout displays original unit price.
    html = client.get("/checkout?productId=p001&purchaseType=GROUP_BUY&startGroupBuy=true").text

    assert "const displayUnitPrice = product.normalPrice;" in html, (
        "Checkout summary should display the original normal price as unit price"
    )
    assert (
        'const payableUnitPrice = purchaseType === "GROUP_BUY" ? '
        "product.groupBuyPrice : product.normalPrice;"
    ) in html, "Group-buy payable should still use the discounted group-buy price"
    assert "money.format(displayUnitPrice)" in html
    assert "money.format(payableUnitPrice)" in html


def test_frontend_checkout_source_sanitizes_quantity_and_recalculates_totals(
    client: TestClient,
) -> None:
    # Covers TC-012, TC-014, Bug 3, and Bug 5 at the SPA source level.
    html = client.get("/checkout?productId=p001&purchaseType=GROUP_BUY&startGroupBuy=true").text

    assert 'inputmode="numeric"' in html
    assert 'pattern="[1-9][0-9]*"' in html
    assert "function sanitizeQuantity()" in html
    assert "getValidQuantity()" in html
    assert "discount * quantity" in html, (
        "Checkout discount display should be multiplied by quantity"
    )
    assert "payableUnitPrice * quantity" in html, (
        "Checkout payable display should be multiplied by quantity"
    )
    assert "Quantity must be a positive whole number." in html


def test_non_creator_cannot_see_or_call_finalize(
    client: TestClient,
) -> None:
    # Covers TC-016 and Bug 6: Finalization is creator-only in UI and API.
    creator_order = start_group_buy_order(client, ALICE, P002)
    group_buy_id = creator_order["groupBuyId"]
    bob_order = join_group_buy(client, BOB, P002, group_buy_id)

    group_buy = get_group_buy(client, group_buy_id)
    assert group_buy["status"] == "READY_TO_CHECKOUT"

    html = client.get(f"/group-buy/{group_buy_id}").text
    assert 'groupBuy.creatorUserId === state.currentUser && groupBuy.status === "READY_TO_CHECKOUT"' in html, (
        "Finalize button should be gated by creator user and ready status"
    )

    denied = finalize_group_buy(client, group_buy_id, BOB, expected_status=400)
    assert denied["detail"] == "ONLY_CREATOR_CAN_FINALIZE"
    assert get_group_buy(client, group_buy_id)["status"] == "READY_TO_CHECKOUT"
    assert get_order(client, creator_order["id"])["status"] == "PENDING_GROUP_BUY"
    assert get_order(client, bob_order["id"])["status"] == "PENDING_GROUP_BUY"


def test_creator_finalize_confirms_all_orders_in_that_group(
    client: TestClient,
) -> None:
    # Covers TC-017: Creator finalizes a ready group and related orders are confirmed.
    creator_order = start_group_buy_order(client, ALICE, P002)
    group_buy_id = creator_order["groupBuyId"]
    join_order = join_group_buy(client, BOB, P002, group_buy_id)

    finalized = finalize_group_buy(client, group_buy_id, ALICE)

    assert finalized["status"] == "SUCCESS"
    assert get_order(client, creator_order["id"])["status"] == "CONFIRMED"
    assert get_order(client, join_order["id"])["status"] == "CONFIRMED"

    late_join = client.post(
        "/api/orders",
        json={
            "userId": CAROL,
            "productId": P002,
            "purchaseType": "GROUP_BUY",
            "groupBuyId": group_buy_id,
            "quantity": 1,
        },
    )
    assert_status(late_join, 400)
    assert late_join.json()["detail"] == "GROUP_BUY_ALREADY_SUCCESS"


def test_creator_cannot_finalize_before_required_size(
    client: TestClient,
) -> None:
    # Covers TC-018: Creator cannot finalize while group is still pending.
    creator_order = start_group_buy_order(client, ALICE, P001)
    group_buy_id = creator_order["groupBuyId"]

    denied = finalize_group_buy(client, group_buy_id, ALICE, expected_status=400)

    assert denied["detail"] == "GROUP_BUY_SIZE_NOT_REACHED"
    assert get_group_buy(client, group_buy_id)["status"] == "PENDING"
    assert get_order(client, creator_order["id"])["status"] == "PENDING_GROUP_BUY"


def test_finalize_scope_is_exact_group_not_same_product(
    client: TestClient,
) -> None:
    # Covers TC-019 and Bug 7: Finalize only confirms orders in the finalized group.
    group_a_creator_order = start_group_buy_order(client, ALICE, P001)
    group_b_creator_order = start_group_buy_order(client, BOB, P001)
    group_a_id = group_a_creator_order["groupBuyId"]
    group_b_id = group_b_creator_order["groupBuyId"]

    group_a_join_carol = join_group_buy(client, CAROL, P001, group_a_id)
    group_a_join_david = join_group_buy(client, DAVID, P001, group_a_id)
    assert get_group_buy(client, group_a_id)["status"] == "READY_TO_CHECKOUT"
    assert get_group_buy(client, group_b_id)["status"] == "PENDING"

    finalized = finalize_group_buy(client, group_a_id, ALICE)

    assert finalized["status"] == "SUCCESS"
    assert get_order(client, group_a_creator_order["id"])["status"] == "CONFIRMED"
    assert get_order(client, group_a_join_carol["id"])["status"] == "CONFIRMED"
    assert get_order(client, group_a_join_david["id"])["status"] == "CONFIRMED"
    assert get_group_buy(client, group_b_id)["status"] == "PENDING"
    assert get_order(client, group_b_creator_order["id"])["status"] == "PENDING_GROUP_BUY", (
        "Finalizing one group must not confirm pending orders from another group for the same product"
    )


def test_group_buy_checkout_rejects_mismatched_or_missing_group_id(
    client: TestClient,
) -> None:
    # Covers TC-021 and TC-022: Group-buy checkout data integrity.
    creator_order = start_group_buy_order(client, ALICE, P001)
    group_buy_id = creator_order["groupBuyId"]

    mismatched = client.post(
        "/api/orders",
        json={
            "userId": BOB,
            "productId": P002,
            "purchaseType": "GROUP_BUY",
            "groupBuyId": group_buy_id,
            "quantity": 1,
        },
    )
    missing = client.post(
        "/api/orders",
        json={
            "userId": BOB,
            "productId": P004,
            "purchaseType": "GROUP_BUY",
            "quantity": 1,
        },
    )

    assert_status(mismatched, 400)
    assert mismatched.json()["detail"] == "GROUP_BUY_PRODUCT_MISMATCH"
    assert_status(missing, 400)
    assert missing.json()["detail"] == "GROUP_BUY_CHECKOUT_REQUIRES_GROUP_BUY_ID"
    assert get_group_buy(client, group_buy_id)["participants"] == [ALICE]
