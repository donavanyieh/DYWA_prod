from fastapi.testclient import TestClient

from app.main import CARTS, ORDERS, app


def test_product_catalog_is_available() -> None:
    client = TestClient(app)

    response = client.get("/api/products")

    assert response.status_code == 200
    products = response.json()
    assert products
    for product in products:
        assert product["id"]
        assert product["name"]
        assert product["price"] > 0


def test_customer_can_add_a_catalog_item_to_cart() -> None:
    CARTS.clear()
    ORDERS.clear()
    client = TestClient(app)

    product = client.get("/api/products").json()[0]
    response = client.post(
        "/api/cart/items",
        json={"product_id": product["id"], "quantity": 1},
    )

    assert response.status_code == 200
    cart = response.json()
    assert cart["items"]
    assert cart["items"][0]["product_id"] == product["id"]
    assert cart["items"][0]["quantity"] == 1
    assert isinstance(cart["total"], int | float)


def test_checkout_rejects_empty_cart() -> None:
    CARTS.clear()
    ORDERS.clear()
    client = TestClient(app)

    response = client.post("/api/checkout")

    assert response.status_code == 400

