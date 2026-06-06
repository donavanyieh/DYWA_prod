from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


app = FastAPI(title="Group Buy Demo Shop")

GroupBuyStatus = Literal["PENDING", "READY_TO_CHECKOUT", "SUCCESS", "EXPIRED"]
PurchaseType = Literal["NORMAL", "GROUP_BUY"]
OrderStatus = Literal["PENDING_GROUP_BUY", "CONFIRMED", "EXPIRED"]


def product_image(primary: str, secondary: str, label: str) -> str:
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 520">
      <defs>
        <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stop-color="{primary}"/>
          <stop offset="1" stop-color="{secondary}"/>
        </linearGradient>
      </defs>
      <rect width="720" height="520" rx="30" fill="url(#bg)"/>
      <circle cx="580" cy="90" r="92" fill="rgba(255,255,255,.18)"/>
      <circle cx="120" cy="420" r="128" fill="rgba(255,255,255,.16)"/>
      <rect x="170" y="130" width="380" height="260" rx="40" fill="rgba(255,255,255,.82)"/>
      <rect x="220" y="180" width="280" height="52" rx="18" fill="{primary}"/>
      <rect x="220" y="258" width="210" height="30" rx="15" fill="{secondary}"/>
      <rect x="220" y="314" width="150" height="30" rx="15" fill="{primary}"/>
      <text x="360" y="456" text-anchor="middle" font-family="Arial" font-size="34" font-weight="700" fill="#ffffff">{label}</text>
    </svg>
    """
    return "data:image/svg+xml;charset=utf-8," + quote(svg)


PRODUCTS = [
    {
        "id": "p001",
        "name": "Wireless Earbuds",
        "description": "Compact wireless earbuds with clear calls, pocket charging, and long battery life.",
        "image_url": product_image("#ff6a00", "#ffb347", "Earbuds"),
        "normal_price": 29.99,
        "group_buy_price": 19.99,
        "required_group_size": 3,
        "rating": 4.8,
        "sold_count": 1280,
        "category": "Audio",
    },
    {
        "id": "p002",
        "name": "Mini Portable Fan",
        "description": "Rechargeable desk fan with three speeds, quiet airflow, and a foldable stand.",
        "image_url": product_image("#17a2b8", "#7dd3fc", "Mini Fan"),
        "normal_price": 15.99,
        "group_buy_price": 10.99,
        "required_group_size": 2,
        "rating": 4.7,
        "sold_count": 864,
        "category": "Lifestyle",
    },
    {
        "id": "p003",
        "name": "Aluminum Phone Stand",
        "description": "Stable adjustable phone stand for video calls, recipes, streaming, and bedside use.",
        "image_url": product_image("#444cf7", "#9aa1ff", "Stand"),
        "normal_price": 9.99,
        "group_buy_price": 6.99,
        "required_group_size": 2,
        "rating": 4.6,
        "sold_count": 2140,
        "category": "Accessories",
    },
    {
        "id": "p004",
        "name": "Insulated Travel Tumbler",
        "description": "Leak-resistant tumbler that keeps drinks cold or warm during commutes and long days.",
        "image_url": product_image("#0f9f6e", "#8ee6bd", "Tumbler"),
        "normal_price": 22.5,
        "group_buy_price": 15.5,
        "required_group_size": 3,
        "rating": 4.9,
        "sold_count": 730,
        "category": "Home",
    },
    {
        "id": "p005",
        "name": "Magnetic Cable Organizer",
        "description": "A tidy desktop cable kit with magnetic clips for chargers, headphones, and USB leads.",
        "image_url": product_image("#f04438", "#fda29b", "Cable Kit"),
        "normal_price": 12.0,
        "group_buy_price": 8.0,
        "required_group_size": 2,
        "rating": 4.5,
        "sold_count": 512,
        "category": "Desk",
    },
]

GROUP_BUYS: dict[str, dict[str, object]] = {}
ORDERS: dict[str, dict[str, object]] = {}


class JoinGroupBuyRequest(BaseModel):
    user_id: str = Field(alias="userId", min_length=1)


class FinalizeGroupBuyRequest(BaseModel):
    user_id: str = Field(alias="userId", min_length=1)


class CreateOrderRequest(BaseModel):
    user_id: str = Field(alias="userId", min_length=1)
    product_id: str = Field(alias="productId")
    purchase_type: PurchaseType = Field(alias="purchaseType")
    group_buy_id: str | None = Field(default=None, alias="groupBuyId")
    start_group_buy: bool = Field(default=False, alias="startGroupBuy")
    quantity: int | str = Field(default=1)


class CreateGroupBuyRequest(BaseModel):
    product_id: str = Field(alias="productId")
    user_id: str = Field(alias="userId", min_length=1)
    quantity: int | str = Field(default=1)


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def deterministic_group_buy_id(product_id: str, creator_user_id: str) -> str:
    return f"{product_id}-{creator_user_id}"


def buggy_quantity(value: int | str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def product_by_id(product_id: str) -> dict[str, object]:
    for product in PRODUCTS:
        if product["id"] == product_id:
            return product
    raise HTTPException(status_code=404, detail="Product not found")


def expire_related_orders(group_buy: dict[str, object]) -> None:
    for order_id in list(group_buy.get("order_ids", [])):
        order = ORDERS.get(str(order_id))
        if order and order["status"] == "PENDING_GROUP_BUY":
            order["status"] = "EXPIRED"


def refresh_group_buy_status(group_buy: dict[str, object]) -> GroupBuyStatus:
    current_status = str(group_buy["status"])
    participants = list(group_buy["participant_user_ids"])
    required_size = int(group_buy["required_group_size"])
    expires_at = group_buy["expires_at"]
    if not isinstance(expires_at, datetime):
        raise HTTPException(status_code=500, detail="Invalid group-buy expiry")

    if current_status == "SUCCESS":
        return "SUCCESS"
    if now_utc() > expires_at:
        group_buy["status"] = "EXPIRED"
        expire_related_orders(group_buy)
    elif len(participants) >= required_size:
        group_buy["status"] = "READY_TO_CHECKOUT"
    else:
        group_buy["status"] = "PENDING"
    return str(group_buy["status"])  # type: ignore[return-value]


def group_buy_by_id(group_buy_id: str) -> dict[str, object]:
    group_buy = GROUP_BUYS.get(group_buy_id)
    if not group_buy:
        raise HTTPException(status_code=404, detail="Group buy not found")
    refresh_group_buy_status(group_buy)
    return group_buy


def public_product(product: dict[str, object]) -> dict[str, object]:
    return {
        "id": product["id"],
        "name": product["name"],
        "description": product["description"],
        "imageUrl": product["image_url"],
        "normalPrice": product["normal_price"],
        "groupBuyPrice": product["group_buy_price"],
        "requiredGroupSize": product["required_group_size"],
        "rating": product["rating"],
        "soldCount": product["sold_count"],
        "category": product["category"],
    }


def public_group_buy(group_buy: dict[str, object], request: Request | None = None) -> dict[str, object]:
    product = product_by_id(str(group_buy["product_id"]))
    participants = list(group_buy["participant_user_ids"])
    required_size = int(group_buy["required_group_size"])
    share_path = f"/group-buy/{group_buy['id']}"
    share_url = str(request.base_url).rstrip("/") + share_path if request else share_path
    return {
        "id": group_buy["id"],
        "groupBuyId": group_buy["id"],
        "productId": product["id"],
        "product": public_product(product),
        "creatorUserId": group_buy["creator_user_id"],
        "participants": participants,
        "participantUserIds": participants,
        "participantCount": len(participants),
        "requiredGroupSize": required_size,
        "remainingSlots": max(required_size - len(participants), 0),
        "status": refresh_group_buy_status(group_buy),
        "createdAt": iso(group_buy["created_at"]),  # type: ignore[arg-type]
        "expiresAt": iso(group_buy["expires_at"]),  # type: ignore[arg-type]
        "shareUrl": share_url,
        "orderIds": list(group_buy.get("order_ids", [])),
    }


def public_order(order: dict[str, object]) -> dict[str, object]:
    product = product_by_id(str(order["product_id"]))
    group_buy = None
    if order.get("group_buy_id"):
        group_buy = public_group_buy(group_buy_by_id(str(order["group_buy_id"])))
    return {
        "id": order["id"],
        "orderId": order["id"],
        "userId": order["user_id"],
        "productId": order["product_id"],
        "product": public_product(product),
        "groupBuyId": order.get("group_buy_id"),
        "purchaseType": order["purchase_type"],
        "unitPrice": order["unit_price"],
        "quantity": order["quantity"],
        "discountAmount": order["discount_amount"],
        "finalPrice": order["final_price"],
        "status": order["status"],
        "createdAt": iso(order["created_at"]),  # type: ignore[arg-type]
        "groupBuy": group_buy,
    }


def create_pending_group_buy_order(
    *,
    product: dict[str, object],
    user_id: str,
    quantity: int | str,
    group_buy_id: str,
) -> dict[str, object]:
    quantity_value = buggy_quantity(quantity)
    unit_price = float(product["group_buy_price"])
    normal_price = float(product["normal_price"])
    order_id = f"ord_{uuid4().hex[:8]}"
    ORDERS[order_id] = {
        "id": order_id,
        "user_id": user_id,
        "product_id": product["id"],
        "group_buy_id": group_buy_id,
        "purchase_type": "GROUP_BUY",
        "unit_price": unit_price,
        "quantity": quantity_value,
        "discount_amount": round(normal_price - unit_price, 2),
        "final_price": round(unit_price, 2),
        "status": "PENDING_GROUP_BUY",
        "created_at": now_utc(),
    }
    return ORDERS[order_id]


def create_group_buy_for_creator(
    *,
    product: dict[str, object],
    creator_user_id: str,
    quantity: int | str = 1,
) -> dict[str, object]:
    group_buy_id = deterministic_group_buy_id(str(product["id"]), creator_user_id)
    created_at = now_utc()
    participant_copies = max(buggy_quantity(quantity), 1)
    GROUP_BUYS[group_buy_id] = {
        "id": group_buy_id,
        "product_id": product["id"],
        "creator_user_id": creator_user_id,
        "participant_user_ids": [creator_user_id for _ in range(participant_copies)],
        "required_group_size": product["required_group_size"],
        "status": "PENDING",
        "created_at": created_at,
        "expires_at": created_at + timedelta(hours=6),
        "order_ids": [],
    }
    return GROUP_BUYS[group_buy_id]


@app.get("/api/products")
def list_products() -> list[dict[str, object]]:
    return [public_product(product) for product in PRODUCTS]


@app.get("/api/products/{product_id}")
def get_product(product_id: str) -> dict[str, object]:
    return public_product(product_by_id(product_id))


@app.get("/api/group-buys/{group_buy_id}")
def get_group_buy(request: Request, group_buy_id: str) -> dict[str, object]:
    return public_group_buy(group_buy_by_id(group_buy_id), request)


@app.post("/api/group-buys")
def create_group_buy_before_checkout(request: Request, payload: CreateGroupBuyRequest) -> dict[str, object]:
    product = product_by_id(payload.product_id)
    group_buy_id = deterministic_group_buy_id(payload.product_id, payload.user_id)
    existing = GROUP_BUYS.get(group_buy_id)
    if existing:
        status = refresh_group_buy_status(existing)
        if status not in {"SUCCESS", "EXPIRED"}:
            return public_group_buy(existing, request)
    group_buy = create_group_buy_for_creator(
        product=product,
        creator_user_id=payload.user_id,
        quantity=payload.quantity,
    )
    refresh_group_buy_status(group_buy)
    return public_group_buy(group_buy, request)


@app.post("/api/group-buys/{group_buy_id}/join")
def join_group_buy(group_buy_id: str, payload: JoinGroupBuyRequest) -> dict[str, object]:
    group_buy = group_buy_by_id(group_buy_id)
    status = refresh_group_buy_status(group_buy)
    if status == "EXPIRED":
        raise HTTPException(status_code=400, detail="GROUP_BUY_EXPIRED")
    if status == "SUCCESS":
        raise HTTPException(status_code=400, detail="GROUP_BUY_ALREADY_SUCCESS")
    if payload.user_id in list(group_buy["participant_user_ids"]):
        raise HTTPException(status_code=400, detail="USER_ALREADY_JOINED_GROUP_BUY")
    return {"status": "checkout_required", "checkoutPath": f"/checkout?purchaseType=GROUP_BUY&groupBuyId={group_buy_id}"}


@app.post("/api/group-buys/{group_buy_id}/finalize")
def finalize_group_buy(request: Request, group_buy_id: str, payload: FinalizeGroupBuyRequest) -> dict[str, object]:
    group_buy = group_buy_by_id(group_buy_id)
    status = refresh_group_buy_status(group_buy)
    if status == "SUCCESS":
        raise HTTPException(status_code=400, detail="GROUP_BUY_ALREADY_SUCCESS")
    if status == "EXPIRED":
        raise HTTPException(status_code=400, detail="GROUP_BUY_EXPIRED")

    participants = list(group_buy["participant_user_ids"])
    if len(participants) < int(group_buy["required_group_size"]):
        raise HTTPException(status_code=400, detail="GROUP_BUY_SIZE_NOT_REACHED")
    if status != "READY_TO_CHECKOUT":
        raise HTTPException(status_code=400, detail="GROUP_BUY_SIZE_NOT_REACHED")

    group_buy["status"] = "SUCCESS"
    for order in ORDERS.values():
        if (
            order["purchase_type"] == "GROUP_BUY"
            and order["product_id"] == group_buy["product_id"]
            and order["status"] == "PENDING_GROUP_BUY"
        ):
            order["status"] = "CONFIRMED"
    return public_group_buy(group_buy, request)


@app.post("/api/orders")
def create_order(request: Request, payload: CreateOrderRequest) -> dict[str, object]:
    product = product_by_id(payload.product_id)
    quantity = buggy_quantity(payload.quantity)

    if payload.purchase_type == "NORMAL":
        unit_price = float(product["normal_price"])
        order_id = f"ord_{uuid4().hex[:8]}"
        ORDERS[order_id] = {
            "id": order_id,
            "user_id": payload.user_id,
            "product_id": payload.product_id,
            "group_buy_id": None,
            "purchase_type": "NORMAL",
            "unit_price": unit_price,
            "quantity": quantity,
            "discount_amount": 0.0,
            "final_price": round(unit_price * quantity, 2),
            "status": "CONFIRMED",
            "created_at": now_utc(),
        }
        return public_order(ORDERS[order_id])

    if payload.start_group_buy:
        group_buy_id = deterministic_group_buy_id(payload.product_id, payload.user_id)
        existing = GROUP_BUYS.get(group_buy_id)
        if existing:
            status = refresh_group_buy_status(existing)
            if status not in {"SUCCESS", "EXPIRED"}:
                return {
                    "existingGroupBuy": True,
                    "message": "Active group buy already exists for this product and creator.",
                    "groupBuy": public_group_buy(existing, request),
                }

        group_buy = create_group_buy_for_creator(
            product=product,
            creator_user_id=payload.user_id,
            quantity=payload.quantity,
        )
        order = create_pending_group_buy_order(
            product=product,
            user_id=payload.user_id,
            quantity=payload.quantity,
            group_buy_id=str(group_buy["id"]),
        )
        group_buy["order_ids"].append(order["id"])  # type: ignore[union-attr]
        refresh_group_buy_status(group_buy)
        return public_order(order)

    if not payload.group_buy_id:
        raise HTTPException(status_code=400, detail="GROUP_BUY_CHECKOUT_REQUIRES_GROUP_BUY_ID")
    group_buy = group_buy_by_id(payload.group_buy_id)
    status = refresh_group_buy_status(group_buy)
    if status == "EXPIRED":
        raise HTTPException(status_code=400, detail="GROUP_BUY_EXPIRED")
    if status == "SUCCESS":
        raise HTTPException(status_code=400, detail="GROUP_BUY_ALREADY_SUCCESS")
    if group_buy["product_id"] != payload.product_id:
        raise HTTPException(status_code=400, detail="GROUP_BUY_PRODUCT_MISMATCH")
    participants = group_buy["participant_user_ids"]
    if not isinstance(participants, list):
        raise HTTPException(status_code=500, detail="Invalid participant list")
    if payload.user_id in participants:
        raise HTTPException(status_code=400, detail="USER_ALREADY_JOINED_GROUP_BUY")

    order = create_pending_group_buy_order(
        product=product,
        user_id=payload.user_id,
        quantity=payload.quantity,
        group_buy_id=payload.group_buy_id,
    )
    participants.append(payload.user_id)
    for _ in range(max(quantity - 1, 0)):
        participants.append(payload.user_id)
    group_buy["order_ids"].append(order["id"])  # type: ignore[union-attr]
    refresh_group_buy_status(group_buy)
    return public_order(order)


@app.get("/api/orders/{order_id}")
def get_order(order_id: str) -> dict[str, object]:
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return public_order(order)


@app.post("/admin/reset")
def reset_state() -> dict[str, object]:
    GROUP_BUYS.clear()
    ORDERS.clear()
    return {"status": "completed", "restored": ["group_buys", "orders"]}


@app.get("/", response_class=HTMLResponse)
@app.get("/products", response_class=HTMLResponse)
@app.get("/products/{product_id}", response_class=HTMLResponse)
@app.get("/group-buy/{group_buy_id}", response_class=HTMLResponse)
@app.get("/checkout", response_class=HTMLResponse)
@app.get("/orders/{order_id}", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>BuyTogether Demo</title>
    <style>
      :root {
        color-scheme: light;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #24160d;
        background: #fff7ed;
      }
      * { box-sizing: border-box; }
      body { margin: 0; min-height: 100vh; background: #fff7ed; }
      button, input, select { font: inherit; }
      button {
        min-height: 42px; border: 0; border-radius: 6px; padding: 0 16px;
        background: #ee4d2d; color: white; font-weight: 800; cursor: pointer;
        box-shadow: 0 8px 18px rgba(238, 77, 45, .18);
      }
      button:hover { background: #d83d20; }
      button:disabled { cursor: not-allowed; background: #c6c0ba; box-shadow: none; }
      button.secondary { background: white; color: #ee4d2d; border: 1px solid #ee4d2d; box-shadow: none; }
      button.ghost { background: #fff3ec; color: #9a3412; box-shadow: none; }
      a { color: inherit; text-decoration: none; }
      .topbar {
        position: sticky; top: 0; z-index: 10; background: #ee4d2d; color: white;
        box-shadow: 0 2px 14px rgba(97, 38, 15, .18);
      }
      .nav {
        max-width: 1180px; margin: 0 auto; padding: 12px 20px; display: flex;
        align-items: center; gap: 18px; justify-content: space-between;
      }
      .brand { display: flex; align-items: center; gap: 10px; font-size: 1.2rem; font-weight: 900; }
      .brand-mark {
        width: 34px; height: 34px; border-radius: 8px; background: white; color: #ee4d2d;
        display: grid; place-items: center; font-weight: 900;
      }
      .user-switcher { display: flex; align-items: center; gap: 8px; font-size: .9rem; }
      .user-switcher select {
        height: 36px; border-radius: 6px; border: 1px solid rgba(255,255,255,.45);
        background: white; color: #74230f; padding: 0 8px; font-weight: 700;
      }
      main { max-width: 1180px; margin: 0 auto; padding: 20px; }
      .hero {
        min-height: 230px; display: grid; align-items: center; padding: 28px;
        background:
          linear-gradient(95deg, rgba(255,255,255,.96) 0 46%, rgba(255,255,255,.58) 67%),
          url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 900 420'%3E%3Crect width='900' height='420' fill='%23ffefe4'/%3E%3Ccircle cx='690' cy='110' r='170' fill='%23ffba8a'/%3E%3Ccircle cx='820' cy='330' r='150' fill='%23ff6a3d'/%3E%3Crect x='520' y='120' width='230' height='160' rx='26' fill='%23ffffff' opacity='.78'/%3E%3Crect x='570' y='165' width='130' height='30' rx='15' fill='%23ee4d2d'/%3E%3Crect x='570' y='220' width='95' height='22' rx='11' fill='%23f97316'/%3E%3C/svg%3E");
        background-size: cover; border-bottom: 1px solid #fed7aa;
      }
      .hero h1 { max-width: 560px; margin: 0 0 10px; font-size: clamp(2rem, 5vw, 4.6rem); line-height: .95; letter-spacing: 0; }
      .hero p { max-width: 560px; margin: 0 0 22px; color: #744022; font-size: 1.05rem; }
      .hero-actions { display: flex; gap: 10px; flex-wrap: wrap; }
      .section-head { display: flex; align-items: end; justify-content: space-between; gap: 14px; margin: 26px 0 14px; }
      .section-head h2 { margin: 0; font-size: 1.4rem; }
      .muted { color: #7c6a5d; }
      .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; }
      .card {
        background: white; border: 1px solid #f3d2bf; border-radius: 8px; overflow: hidden;
        box-shadow: 0 8px 20px rgba(112, 66, 32, .08);
      }
      .product-card { display: grid; grid-template-rows: 170px 1fr; }
      .product-card img { width: 100%; height: 170px; object-fit: cover; display: block; background: #fff2e8; }
      .product-body { padding: 12px; display: grid; gap: 8px; }
      .product-title { min-height: 44px; margin: 0; font-size: 1rem; line-height: 1.25; }
      .badge {
        display: inline-flex; align-items: center; width: fit-content; min-height: 24px;
        border-radius: 4px; padding: 0 7px; background: #fff1e8; color: #c2410c;
        border: 1px solid #fed7aa; font-size: .78rem; font-weight: 800;
      }
      .price-row { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
      .deal-price { color: #ee4d2d; font-size: 1.45rem; font-weight: 900; }
      .normal-price { color: #8b7b70; text-decoration: line-through; }
      .meta-row { display: flex; justify-content: space-between; gap: 8px; color: #7c6a5d; font-size: .9rem; }
      .detail { display: grid; grid-template-columns: minmax(280px, 1.05fr) minmax(320px, .95fr); gap: 18px; align-items: start; }
      .detail-image { width: 100%; aspect-ratio: 1.15; object-fit: cover; border-radius: 8px; border: 1px solid #f3d2bf; background: white; }
      .panel { background: white; border: 1px solid #f3d2bf; border-radius: 8px; padding: 18px; box-shadow: 0 8px 20px rgba(112, 66, 32, .08); }
      .panel h1, .panel h2 { margin-top: 0; }
      .actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
      .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 16px 0; }
      .stat { background: #fff7ed; border: 1px solid #fed7aa; border-radius: 6px; padding: 10px; }
      .stat strong { display: block; font-size: 1.15rem; color: #9a3412; }
      .status { font-size: .8rem; font-weight: 900; border-radius: 4px; padding: 4px 8px; width: fit-content; }
      .status.PENDING { background: #fff7d6; color: #854d0e; }
      .status.READY_TO_CHECKOUT { background: #dbeafe; color: #1d4ed8; }
      .status.SUCCESS { background: #dcfce7; color: #166534; }
      .status.EXPIRED { background: #fee2e2; color: #991b1b; }
      .share-box { display: grid; grid-template-columns: 1fr auto; gap: 8px; margin-top: 14px; }
      .share-box input, .field input {
        width: 100%; height: 42px; border-radius: 6px; border: 1px solid #e8c6b5; padding: 0 10px;
        background: #fffaf6; color: #24160d;
      }
      .checkout-grid { display: grid; grid-template-columns: 1.1fr .9fr; gap: 18px; }
      .summary-row { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid #f3d2bf; }
      .summary-row.total { border-bottom: 0; font-size: 1.15rem; font-weight: 900; color: #ee4d2d; }
      .notice { margin: 14px 0; padding: 12px; border-radius: 6px; background: #fff1e8; color: #9a3412; border: 1px solid #fed7aa; }
      .error { margin: 14px 0; padding: 12px; border-radius: 6px; background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }
      @media (max-width: 760px) {
        .nav { align-items: flex-start; flex-direction: column; }
        main { padding: 14px; }
        .hero { padding: 22px 16px; }
        .detail, .checkout-grid { grid-template-columns: 1fr; }
        .stats { grid-template-columns: 1fr; }
        .share-box { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <header class="topbar">
      <nav class="nav">
        <a class="brand" href="/" data-link><span class="brand-mark">BT</span><span>BuyTogether</span></a>
        <label class="user-switcher">
          Mock user
          <select id="userSelect" data-testid="mock-user-switcher">
            <option value="u001">u001</option>
            <option value="u002">u002</option>
            <option value="u003">u003</option>
            <option value="u004">u004</option>
          </select>
        </label>
      </nav>
    </header>
    <div id="app"></div>
    <script>
      const app = document.querySelector("#app");
      const userSelect = document.querySelector("#userSelect");
      const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
      const state = { products: [], currentUser: localStorage.getItem("mockUserId") || "u001" };
      userSelect.value = state.currentUser;

      userSelect.addEventListener("change", () => {
        state.currentUser = userSelect.value;
        localStorage.setItem("mockUserId", state.currentUser);
        renderRoute();
      });

      window.addEventListener("popstate", renderRoute);
      document.addEventListener("click", event => {
        const link = event.target.closest("a[data-link]");
        if (!link) return;
        event.preventDefault();
        navigate(link.getAttribute("href"));
      });

      function navigate(path) {
        history.pushState({}, "", path);
        renderRoute();
      }

      async function api(path, options = {}) {
        const response = await fetch(path, {
          headers: { \"Content-Type\": \"application/json\" },
          ...options
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "Request failed");
        return data;
      }

      function page(content) {
        app.innerHTML = `<main>${content}</main>`;
      }

      function showError(message) {
        page(`<div class="error" data-testid="error-message">${message}</div><p><a href="/" data-link>Back to products</a></p>`);
      }

      async function ensureProducts() {
        if (!state.products.length) state.products = await api("/api/products");
        return state.products;
      }

      function productCard(product) {
        return `
          <article class="card product-card" data-testid="product-card">
            <img src="${product.imageUrl}" alt="${product.name}">
            <div class="product-body">
              <span class="badge">Group Buy Deal</span>
              <h3 class="product-title">${product.name}</h3>
              <div class="price-row">
                <span class="deal-price">${money.format(product.groupBuyPrice)}</span>
                <span class="normal-price">${money.format(product.normalPrice)}</span>
              </div>
              <div class="meta-row"><span>${product.rating} rating</span><span>${product.soldCount} sold</span></div>
              <button type="button" onclick="navigate('/products/${product.id}')" data-testid="view-details-button">View details</button>
            </div>
          </article>
        `;
      }

      async function renderListing() {
        const products = await ensureProducts();
        page(`
          <section class="hero">
            <div>
              <h1>Buy together and unlock better prices</h1>
              <p>Checkout first to create a group-buy link, then share it so friends can join.</p>
              <div class="hero-actions">
                <button type="button" onclick="document.querySelector('#deals').scrollIntoView()">Shop group deals</button>
                <button class="secondary" type="button" onclick="navigate('/products/${products[0].id}')">Start with earbuds</button>
              </div>
            </div>
          </section>
          <section id="deals">
            <div class="section-head">
              <div>
                <h2>Today&apos;s Group Buy Picks</h2>
                <div class="muted">Checkout-gated links, creator finalization, and clear order states.</div>
              </div>
              <span class="badge">${products.length} products</span>
            </div>
            <div class="grid">${products.map(productCard).join("")}</div>
          </section>
        `);
      }

      async function renderProduct(productId) {
        const product = await api(`/api/products/${productId}`);
        page(`
          <section class="detail">
            <img class="detail-image" src="${product.imageUrl}" alt="${product.name}">
            <article class="panel">
              <span class="badge">${product.category}</span>
              <h1>${product.name}</h1>
              <p class="muted">${product.description}</p>
              <div class="price-row">
                <span class="deal-price">${money.format(product.groupBuyPrice)}</span>
                <span class="normal-price">${money.format(product.normalPrice)}</span>
              </div>
              <div class="stats">
                <div class="stat"><strong>${product.rating}</strong><span>Rating</span></div>
                <div class="stat"><strong>${product.requiredGroupSize}</strong><span>Group size</span></div>
                <div class="stat"><strong>${product.soldCount}</strong><span>Sold</span></div>
              </div>
              <div class="notice">Group-buy links are generated only after ${state.currentUser} completes checkout.</div>
              <div class="actions">
                <button type="button" onclick="startGroupBuyBeforeCheckout('${product.id}')" data-testid="start-group-buy-button">Group Buy</button>
                <button class="secondary" type="button" onclick="goCheckout('${product.id}', 'NORMAL')">Buy Now</button>
                <button class="ghost" type="button" onclick="navigate('/')">Back</button>
              </div>
            </article>
          </section>
        `);
      }

      async function startGroupBuyBeforeCheckout(productId) {
        try {
          const groupBuy = await api("/api/group-buys", {
            method: "POST",
            body: JSON.stringify({ productId, userId: state.currentUser, quantity: 1 })
          });
          navigate(`/group-buy/${groupBuy.id}`);
        } catch (error) {
          showError(error.message);
        }
      }

      async function renderGroupBuy(groupBuyId) {
        const groupBuy = await api(`/api/group-buys/${groupBuyId}`);
        const product = groupBuy.product;
        const alreadyJoined = groupBuy.participants.includes(state.currentUser);
        const canJoin = !alreadyJoined && !["SUCCESS", "EXPIRED"].includes(groupBuy.status);
        const canFinalize = groupBuy.status === "READY_TO_CHECKOUT";
        page(`
          <section class="detail">
            <img class="detail-image" src="${product.imageUrl}" alt="${product.name}">
            <article class="panel">
              <span class="status ${groupBuy.status}" data-testid="group-buy-status">${groupBuy.status}</span>
              <h1>${product.name}</h1>
              <p class="muted">Creator: <strong data-testid="creator-user-id">${groupBuy.creatorUserId}</strong></p>
              <div class="price-row">
                <span class="deal-price">${money.format(product.groupBuyPrice)}</span>
                <span class="normal-price">${money.format(product.normalPrice)}</span>
              </div>
              <div class="stats">
                <div class="stat"><strong data-testid="participant-count">${groupBuy.participantCount}</strong><span>Joined</span></div>
                <div class="stat"><strong>${groupBuy.requiredGroupSize}</strong><span>Required</span></div>
              </div>
              <p class="muted">Expires at ${new Date(groupBuy.expiresAt).toLocaleString()}</p>
              <div class="share-box">
                <input id="shareLink" readonly value="${groupBuy.shareUrl}" data-testid="share-link">
                <button class="secondary" type="button" onclick="copyShareLink()">Copy</button>
              </div>
              <div class="notice">${alreadyJoined ? `Current user ${state.currentUser} has checked out for this deal.` : `Current user ${state.currentUser} can join by completing checkout.`}</div>
              <div class="actions">
                <button type="button" onclick="goCheckout('${product.id}', 'GROUP_BUY', '${groupBuy.id}')" data-testid="join-group-buy-button" ${canJoin ? "" : "disabled"}>Join Group Buy</button>
                ${canFinalize ? `<button class="secondary" type="button" onclick="finalizeGroupBuy('${groupBuy.id}')" data-testid="finalize-group-buy-button">Finalize Group Buy</button>` : ""}
              </div>
            </article>
          </section>
        `);
      }

      async function copyShareLink() {
        const input = document.querySelector("#shareLink");
        input.select();
        await navigator.clipboard?.writeText(input.value).catch(() => {});
      }

      async function finalizeGroupBuy(groupBuyId) {
        try {
          await api(`/api/group-buys/${groupBuyId}/finalize`, {
            method: "POST",
            body: JSON.stringify({ userId: state.currentUser })
          });
          renderGroupBuy(groupBuyId);
        } catch (error) {
          showError(error.message);
        }
      }

      function goCheckout(productId, purchaseType, groupBuyId = "", startGroupBuy = false) {
        const params = new URLSearchParams({ productId, purchaseType });
        if (groupBuyId) params.set("groupBuyId", groupBuyId);
        if (startGroupBuy) params.set("startGroupBuy", "true");
        navigate(`/checkout?${params.toString()}`);
      }

      async function renderCheckout() {
        const params = new URLSearchParams(location.search);
        const productId = params.get("productId");
        const purchaseType = params.get("purchaseType") || "NORMAL";
        const groupBuyId = params.get("groupBuyId");
        const startGroupBuy = params.get("startGroupBuy") === "true";
        if (!productId) return showError("Checkout requires a product.");
        const product = await api(`/api/products/${productId}`);
        const displayUnitPrice = product.normalPrice;
        const payableUnitPrice = purchaseType === "GROUP_BUY" ? product.groupBuyPrice : product.normalPrice;
        const discount = purchaseType === "GROUP_BUY" ? product.normalPrice - product.groupBuyPrice : 0;
        const title = startGroupBuy ? "Start Group Buy Checkout" : purchaseType === "GROUP_BUY" ? "Join Group Buy Checkout" : "Checkout";
        page(`
          <section class="checkout-grid">
            <article class="panel">
              <h1>${title}</h1>
              <p class="muted">Mock delivery to 123 Demo Street, Singapore.</p>
              <div class="field">
                <label>Quantity</label>
                <input id="quantity" type="text" inputmode="numeric" pattern="[1-9][0-9]*" value="1" data-testid="quantity-input" oninput="sanitizeQuantity(); updateCheckoutSummary(${payableUnitPrice}, ${discount})">
              </div>
              <div class="actions">
                <button type="button" onclick="placeOrder('${product.id}', '${purchaseType}', '${groupBuyId || ""}', ${startGroupBuy})" data-testid="place-order-button">Place Order</button>
                <button class="ghost" type="button" onclick="navigate('/products/${product.id}')">Cancel</button>
              </div>
            </article>
            <article class="panel">
              <h2>Order Summary</h2>
              <div class="summary-row"><span>Product</span><strong>${product.name}</strong></div>
              <div class="summary-row"><span>Purchase type</span><strong data-testid="purchase-type">${purchaseType}</strong></div>
              <div class="summary-row"><span>Unit price</span><strong>${money.format(displayUnitPrice)}</strong></div>
              <div class="summary-row"><span>Discount</span><strong id="discount">${money.format(discount)}</strong></div>
              <div class="summary-row total"><span>Payable</span><span id="payable" data-testid="final-payable">${money.format(payableUnitPrice)}</span></div>
            </article>
          </section>
        `);
      }

      function sanitizeQuantity() {
        const input = document.querySelector("#quantity");
        input.value = input.value.replace(/[^0-9]/g, "").replace(/^0+/, "");
      }

      function getValidQuantity() {
        const input = document.querySelector("#quantity");
        sanitizeQuantity();
        const quantity = Number(input.value);
        if (!Number.isInteger(quantity) || quantity < 1) {
          throw new Error("Quantity must be a positive whole number.");
        }
        return quantity;
      }

      function updateCheckoutSummary(payableUnitPrice, discount) {
        let quantity = 1;
        try {
          quantity = getValidQuantity();
        } catch (_error) {
          document.querySelector("#discount").textContent = money.format(0);
          document.querySelector("#payable").textContent = money.format(0);
          return;
        }
        document.querySelector("#discount").textContent = money.format(discount * quantity);
        document.querySelector("#payable").textContent = money.format(payableUnitPrice * quantity);
      }

      async function placeOrder(productId, purchaseType, groupBuyId, startGroupBuy) {
        try {
          const quantity = document.querySelector("#quantity").value;
          const result = await api("/api/orders", {
            method: "POST",
            body: JSON.stringify({
              userId: state.currentUser,
              productId,
              purchaseType,
              groupBuyId: groupBuyId || undefined,
              startGroupBuy,
              quantity
            })
          });
          if (result.existingGroupBuy) {
            navigate(`/group-buy/${result.groupBuy.id}`);
            return;
          }
          navigate(`/orders/${result.id}`);
        } catch (error) {
          showError(error.message);
        }
      }

      async function renderOrder(orderId) {
        const order = await api(`/api/orders/${orderId}`);
        page(`
          <article class="panel">
            <span class="badge">Order Created</span>
            <h1 data-testid="order-id">${order.id}</h1>
            <p>${order.product.name}</p>
            <div class="summary-row"><span>Order status</span><strong data-testid="order-status">${order.status}</strong></div>
            <div class="summary-row"><span>Final paid price</span><strong data-testid="final-paid-price">${money.format(order.finalPrice)}</strong></div>
            <div class="summary-row"><span>Purchase type</span><strong>${order.purchaseType}</strong></div>
            ${order.groupBuy ? `<div class="summary-row"><span>Group-buy status</span><strong data-testid="order-group-buy-status">${order.groupBuy.status}</strong></div>` : ""}
            ${order.groupBuy ? `<div class="share-box"><input readonly value="${order.groupBuy.shareUrl}" data-testid="order-group-buy-link"><button class="secondary" type="button" onclick="navigate('/group-buy/${order.groupBuy.id}')">View Group Buy</button></div>` : ""}
            <div class="notice">${order.purchaseType === "GROUP_BUY" ? "Your group-buy order is pending until the creator finalizes the deal." : `Your mock payment is confirmed for ${state.currentUser}.`}</div>
            <div class="actions">
              <button type="button" onclick="navigate('/')">Continue shopping</button>
              ${order.groupBuyId ? `<button class="secondary" type="button" onclick="navigate('/group-buy/${order.groupBuyId}')">Back to Group Buy</button>` : ""}
            </div>
          </article>
        `);
      }

      async function renderRoute() {
        try {
          const path = location.pathname;
          if (path === "/" || path === "/products") return renderListing();
          if (path.startsWith("/products/")) return renderProduct(path.split("/")[2]);
          if (path.startsWith("/group-buy/")) return renderGroupBuy(path.split("/")[2]);
          if (path === "/checkout") return renderCheckout();
          if (path.startsWith("/orders/")) return renderOrder(path.split("/")[2]);
          showError("Page not found.");
        } catch (error) {
          showError(error.message);
        }
      }

      renderRoute();
    </script>
  </body>
</html>
"""
