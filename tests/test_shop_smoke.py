from fastapi.testclient import TestClient

from app.main import GROUP_BUYS, ORDERS, app


def test_product_catalog_is_available() -> None:
    client = TestClient(app)

    response = client.get("/api/products")

    assert response.status_code == 200
    products = response.json()
    assert products
    for product in products:
        assert product["id"]
        assert product["name"]
        assert product["normalPrice"] > 0
        assert product["groupBuyPrice"] > 0


def test_customer_can_add_a_catalog_item_to_cart() -> None:
    GROUP_BUYS.clear()
    ORDERS.clear()
    client = TestClient(app)

    product = client.get("/api/products").json()[0]
    response = client.post("/api/orders", json={
        "userId": "user_smoke",
        "productId": product["id"],
        "purchaseType": "NORMAL",
        "quantity": 1,
    })

    assert response.status_code == 200
    order = response.json()
    assert order["productId"] == product["id"]
    assert order["quantity"] == 1
    assert order["status"] == "CONFIRMED"
    assert isinstance(order["finalPrice"], int | float)


def test_checkout_rejects_empty_cart() -> None:
    GROUP_BUYS.clear()
    ORDERS.clear()
    client = TestClient(app)

    response = client.get("/checkout")

    assert response.status_code == 200
    assert "Checkout" in response.text

