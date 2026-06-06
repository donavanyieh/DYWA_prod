from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


app = FastAPI(title="Adaptive Healing Demo Shop")

PRODUCTS = [
    {
        "id": "phone_case_blue",
        "name": "Blue Shockproof Phone Case",
        "price": 12.5,
        "category": "Accessories",
    },
    {
        "id": "wireless_charger",
        "name": "Compact Wireless Charger",
        "price": 24.0,
        "category": "Electronics",
    },
    {
        "id": "canvas_tote",
        "name": "Everyday Canvas Tote",
        "price": 18.75,
        "category": "Bags",
    },
]

CARTS: dict[str, dict[str, int]] = {}
ORDERS: list[dict[str, object]] = []


class AddCartItemRequest(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=99)


class UpdateCartItemRequest(BaseModel):
    quantity: int = Field(ge=0, le=99)


def product_by_id(product_id: str) -> dict[str, object]:
    for product in PRODUCTS:
        if product["id"] == product_id:
            return product
    raise HTTPException(status_code=404, detail="Product not found")


def session_cart(session_id: str) -> dict[str, int]:
    return CARTS.setdefault(session_id, {})


def get_or_create_session_id(response: Response, session_id: str | None) -> str:
    if session_id:
        return session_id
    new_session_id = f"sess_{uuid4().hex}"
    response.set_cookie("session_id", new_session_id, httponly=True, samesite="lax")
    return new_session_id


def calculate_cart_total(cart: dict[str, int]) -> float:
    total = 0.0
    for product_id, quantity in cart.items():
        product = product_by_id(product_id)
        total += float(product["price"]) * quantity
    return round(total, 2)


def cart_payload(cart: dict[str, int]) -> dict[str, object]:
    items = []
    for product_id, quantity in cart.items():
        product = product_by_id(product_id)
        unit_price = float(product["price"])
        items.append(
            {
                "product_id": product_id,
                "name": product["name"],
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": round(unit_price * quantity, 2),
            }
        )
    return {"items": items, "total": calculate_cart_total(cart)}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Demo Shop</title>
    <style>
      :root { font-family: Arial, Helvetica, sans-serif; color: #18202a; }
      body { margin: 0; background: #f6f8fb; }
      header { background: #0f766e; color: white; padding: 18px 24px; }
      main { max-width: 980px; margin: 0 auto; padding: 24px; }
      .layout { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; }
      .products, .cart { display: grid; gap: 12px; }
      .product, .cart-panel, .order-panel {
        background: white; border: 1px solid #d8dee8; border-radius: 8px; padding: 16px;
      }
      button {
        border: 0; border-radius: 8px; background: #0f766e; color: white;
        cursor: pointer; font-weight: 700; padding: 10px 12px;
      }
      button.secondary { background: #335c67; }
      input { border: 1px solid #b8c0cc; border-radius: 6px; padding: 8px; width: 64px; }
      .muted { color: #667085; }
      .total { font-size: 1.35rem; font-weight: 800; }
      @media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
    </style>
  </head>
  <body>
    <header><strong>Demo Shop</strong></header>
    <main>
      <div class="layout">
        <section>
          <h1>Products</h1>
          <div id="products" class="products"></div>
        </section>
        <aside>
          <h2>Cart</h2>
          <div id="cart" class="cart-panel"></div>
          <p><button id="checkout" class="secondary" type="button" disabled>Checkout</button></p>
          <div id="order" class="order-panel muted">No order yet.</div>
        </aside>
      </div>
    </main>
    <script>
      const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

      async function api(path, options = {}) {
        const response = await fetch(path, {
          headers: { "Content-Type": "application/json" },
          ...options
        });
        if (!response.ok) throw new Error(await response.text());
        return response.json();
      }

      async function loadProducts() {
        const products = await api("/api/products");
        document.querySelector("#products").innerHTML = products.map(product => `
          <article class="product">
            <h2>${product.name}</h2>
            <p class="muted">${product.category}</p>
            <p><strong>${money.format(product.price)}</strong></p>
            <button type="button" onclick="addToCart('${product.id}')">Add to cart</button>
          </article>
        `).join("");
      }

      async function loadCart() {
        const cart = await api("/api/cart");
        const checkoutBtn = document.querySelector("#checkout");
        if (!cart.items.length) {
          document.querySelector("#cart").innerHTML = "<p class='muted'>Your cart is empty.</p>";
          checkoutBtn.disabled = true;
          return;
        }
        checkoutBtn.disabled = false;
        document.querySelector("#cart").innerHTML = `
          ${cart.items.map(item => `
            <div>
              <strong>${item.name}</strong>
              <p class="muted">Unit ${money.format(item.unit_price)} | Subtotal ${money.format(item.subtotal)}</p>
              <label>
                Quantity
                <input type="number" min="0" max="99" value="${item.quantity}"
                  onchange="updateQuantity('${item.product_id}', this.value)">
              </label>
            </div>
          `).join("<hr>")}
          <p class="total">Total: ${money.format(cart.total)}</p>
        `;
      }

      async function addToCart(productId) {
        await api("/api/cart/items", {
          method: "POST",
          body: JSON.stringify({ product_id: productId, quantity: 1 })
        });
        await loadCart();
      }

      async function updateQuantity(productId, quantity) {
        await api(`/api/cart/items/${productId}`, {
          method: "PATCH",
          body: JSON.stringify({ quantity: Number(quantity) })
        });
        await loadCart();
      }

      async function checkout() {
        // Guard on client: prevent checkout if the cart is empty
        const currentCart = await api("/api/cart");
        if (!currentCart.items.length) {
          document.querySelector("#order").innerHTML = "<em>Please add items to your cart before checkout.</em>";
          return;
        }
        const order = await api("/api/checkout", { method: "POST" });
        document.querySelector("#order").innerHTML =
          `<strong>Order ${order.order_id}</strong><p>Total charged: ${money.format(order.total)}</p>`;
        await loadCart();
      }

      document.querySelector("#checkout").addEventListener("click", checkout);
      loadProducts();
      loadCart();
    </script>
  </body>
</html>
"""


@app.get("/api/products")
def list_products() -> list[dict[str, object]]:
    return PRODUCTS


@app.get("/api/cart")
def get_cart(
    response: Response,
    session_id: Annotated[str | None, Cookie(alias="session_id")] = None,
) -> dict[str, object]:
    current_session = get_or_create_session_id(response, session_id)
    return cart_payload(session_cart(current_session))


@app.post("/api/cart/items")
def add_cart_item(
    request: AddCartItemRequest,
    response: Response,
    session_id: Annotated[str | None, Cookie(alias="session_id")] = None,
) -> dict[str, object]:
    product_by_id(request.product_id)
    current_session = get_or_create_session_id(response, session_id)
    cart = session_cart(current_session)
    cart[request.product_id] = cart.get(request.product_id, 0) + request.quantity
    return cart_payload(cart)


@app.patch("/api/cart/items/{product_id}")
def update_cart_item(
    product_id: str,
    request: UpdateCartItemRequest,
    response: Response,
    session_id: Annotated[str | None, Cookie(alias="session_id")] = None,
) -> dict[str, object]:
    product_by_id(product_id)
    current_session = get_or_create_session_id(response, session_id)
    cart = session_cart(current_session)
    if request.quantity == 0:
        cart.pop(product_id, None)
    else:
        cart[product_id] = request.quantity
    return cart_payload(cart)


@app.post("/api/checkout")
def checkout(
    response: Response,
    session_id: Annotated[str | None, Cookie(alias="session_id")] = None,
) -> dict[str, object]:
    current_session = get_or_create_session_id(response, session_id)
    cart = session_cart(current_session)
    if not cart:
        raise HTTPException(status_code=400, detail="Cart is empty")
    order = {
        "order_id": f"ord_{uuid4().hex[:8]}",
        "items": cart_payload(cart)["items"],
        "total": calculate_cart_total(cart),
    }
    ORDERS.append(order)
    CARTS[current_session] = {}
    return order


@app.post("/admin/reset")
def reset_state() -> dict[str, object]:
    CARTS.clear()
    ORDERS.clear()
    return {"status": "completed", "restored": ["in_memory_cart", "orders"]}
