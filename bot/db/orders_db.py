#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import atexit
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from utils.config import BOT_OWNER

# TinyDB persistence (installed via requirements)
try:
    from tinydb import TinyDB, Query
    from tinydb.table import Document
    from tinydb.storages import JSONStorage
except Exception:
    TinyDB = None  # type: ignore
    Document = dict  # type: ignore

# ========== CONFIG ==========
# New TinyDB storage file
TINYDB_FILE = Path(__file__).parent / "orders_db.json"

# Table names
TBL_USERS = "users"
TBL_PRODUCTS = "products"
TBL_ORDERS = "orders"          # current orders
TBL_OLD_ORDERS = "old_orders"   # past orders
TBL_REG = "registration"
TBL_META = "meta"               # single doc with flags/passwords/schema

# ========== GLOBAL DATA (in-memory) ==========
DATA = None
DATA_DIRTY = False
_DB = None  # TinyDB instance

def _db():
    _ensure_db_initialized()
    return _DB  # type: ignore[return-value]

def _tbl(name: str):
    return _db().table(name)

def _meta_get(key: str, default=None):
    meta = _tbl(TBL_META).get(doc_id=1) or {}
    return meta.get(key, default)

def _meta_set(key: str, value):
    meta_table = _tbl(TBL_META)
    doc = meta_table.get(doc_id=1) or {}
    doc[key] = value
    if meta_table.get(doc_id=1) is None:
        meta_table.insert(Document(doc, doc_id=1))
    else:
        meta_table.update(doc, doc_ids=[1])

def _ensure_db_initialized():
    """
    Initialize TinyDB and ensure required tables/meta exist.
    No legacy migration logic is retained.
    """
    global _DB
    if _DB is not None:
        return
    if TinyDB is None:
        # TinyDB not installed; runtime operations will fail
        raise RuntimeError("TinyDB is not installed. Please add 'tinydb' to requirements and install it.")

    # Ensure parent directory exists
    TINYDB_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Human-readable storage that writes arrays and a meta dict
    class HumanJSONStorage(JSONStorage):
        def _tables_to_simple(self, data: Dict[str, Any]) -> Dict[str, Any]:
            # data: { table_name: { doc_id: doc, ... }, ... }
            def to_list(table_name: str) -> List[Dict[str, Any]]:
                table = data.get(table_name) or {}
                # sort by numeric doc_id if possible for stability
                def _key(k):
                    try:
                        return int(k)
                    except Exception:
                        return 0
                return [table[k] for k in sorted(table.keys(), key=_key)]

            simple = {
                "users": to_list(TBL_USERS),
                "products": to_list(TBL_PRODUCTS),
                "collections": to_list(TBL_ORDERS),
                "old_collections": to_list(TBL_OLD_ORDERS),
                "registration": to_list(TBL_REG),
                "meta": (data.get(TBL_META, {}) or {}).get("1") or (data.get(TBL_META, {}) or {}).get(1) or {
                    "collection_open": False,
                    "auth_password": None,
                    "schema_version": 2,
                },
            }
            return simple

        def _simple_to_tables(self, simple: Dict[str, Any]) -> Dict[str, Any]:
            # Convert from simplified arrays/meta to TinyDB internal form
            def from_list(arr: List[Dict[str, Any]]) -> Dict[str, Any]:
                out: Dict[str, Any] = {}
                i = 1
                for item in (arr or []):
                    out[str(i)] = item
                    i += 1
                return out

            tables: Dict[str, Any] = {
                TBL_USERS: from_list(simple.get("users") or []),
                TBL_PRODUCTS: from_list(simple.get("products") or []),
                TBL_ORDERS: from_list(simple.get("collections") or []),
                TBL_OLD_ORDERS: from_list(simple.get("old_collections") or []),
                TBL_REG: from_list(simple.get("registration") or []),
                TBL_META: {"1": simple.get("meta") or {}},
            }
            # Keep _default empty to satisfy TinyDB invariants
            tables.setdefault("_default", {})
            return tables

        def read(self):  # type: ignore[override]
            try:
                self._handle.seek(0)
                raw = json.load(self._handle)
            except Exception:
                return None
            # Detect if it's already TinyDB format (has per-table dicts)
            if isinstance(raw, dict) and any(isinstance(v, dict) and any(isinstance(x, dict) for x in v.values()) for v in raw.values()):
                return raw
            # Otherwise, assume simplified format and convert
            if isinstance(raw, dict) and ("users" in raw or "collections" in raw or "meta" in raw):
                return self._simple_to_tables(raw)
            return raw

        def write(self, data):  # type: ignore[override]
            # Overwrite file with human-readable simplified JSON
            self._handle.seek(0)
            self._handle.truncate()
            simple = self._tables_to_simple(data or {})
            json.dump(simple, self._handle, ensure_ascii=False, indent=2)

    _DB = TinyDB(TINYDB_FILE, storage=HumanJSONStorage)

    # Ensure meta doc exists with defaults
    if _tbl(TBL_META).get(doc_id=1) is None:
        _tbl(TBL_META).insert(Document({
            "schema_version": 2,
            "collection_open": False,
            "auth_password": None,
        }, doc_id=1))

# ========== DATA STRUCTURES ==========
@dataclass
class Product:
    """Структура товара"""
    product_id: int
    title: str
    price: int
    link: str

    def __hash__(self):
        return hash(self.product_id)

    def __eq__(self, other):
        if not isinstance(other, Product):
            return False
        return self.product_id == other.product_id

    class Fields(Enum):
        """Поля товара в каталоге products"""
        PRODUCT_ID = "product_id"
        TITLE = "title"
        PRICE = "price"
        LINK = "link"

    @classmethod
    def from_record(cls, record: dict) -> 'Product':
        return cls(
            product_id=int(record.get(Product.Fields.PRODUCT_ID.value, 0)),
            title=record.get(Product.Fields.TITLE.value, ""),
            price=int(record.get(Product.Fields.PRICE.value, 0)),
            link=record.get(Product.Fields.LINK.value, ""),
        )

    def to_record(self) -> dict:
        return {
            Product.Fields.PRODUCT_ID.value: self.product_id,
            Product.Fields.TITLE.value: self.title,
            Product.Fields.PRICE.value: self.price,
            Product.Fields.LINK.value: self.link,
        }
@dataclass
class UserOrder:
    """Структура заказа (только ссылки на товар + количество/статус)"""
    user_id: int
    product_id: int
    count: int
    done: bool = False

    class Fields(Enum):
        """Поля заказа пользователя"""
        USER_ID = "user_id"
        PRODUCT_ID = "product_id"
        COUNT = "count"
        DONE = "done"

    @classmethod
    def from_record(cls, record: dict) -> 'UserOrder':
        return cls(
            user_id=int(record.get(UserOrder.Fields.USER_ID.value, 0)),
            product_id=int(record.get(UserOrder.Fields.PRODUCT_ID.value, 0)),
            count=int(record.get(UserOrder.Fields.COUNT.value, 1)),
            done=bool(record.get(UserOrder.Fields.DONE.value, False))
        )

    def to_record(self) -> dict:
        return {
            UserOrder.Fields.USER_ID.value: self.user_id,
            UserOrder.Fields.PRODUCT_ID.value: self.product_id,
            UserOrder.Fields.COUNT.value: self.count,
            UserOrder.Fields.DONE.value: self.done
        }

@dataclass
class User:
    """Структура пользователя"""
    user_id: int
    name: str
    is_admin: bool = False

    def __hash__(self):
        return hash(self.user_id)

    def __eq__(self, other):
        if not isinstance(other, User):
            return False
        return self.user_id == other.user_id

    class Fields(Enum):
        """Поля пользователя"""
        USER_ID = "user_id"
        NAME = "name"
        IS_ADMIN = "is_admin"

    @classmethod
    def from_record(cls, record: dict) -> 'User':
        return cls(
            user_id=int(record.get(User.Fields.USER_ID.value, 0)),
            name=record.get(User.Fields.NAME.value, ""),
            is_admin=bool(record.get(User.Fields.IS_ADMIN.value, False))
        )

    def to_record(self) -> dict:
        return {
            User.Fields.USER_ID.value: self.user_id,
            User.Fields.NAME.value: self.name,
            User.Fields.IS_ADMIN.value: self.is_admin
        }

@dataclass
class Registration:
    """Регистрация пользователя: попытки входа и флаг блокировки"""
    user_id: int
    attempts: int = 0
    blacklisted: bool = False

    @classmethod
    def from_record(cls, record: dict) -> 'Registration':
        return cls(
            user_id=int(record.get("user_id", 0)),
            attempts=int(record.get("attempts", 0)),
            blacklisted=bool(record.get("blacklisted", False)),
        )

    def to_record(self) -> dict:
        return {
            "user_id": self.user_id,
            "attempts": self.attempts,
            "blacklisted": self.blacklisted,
        }

@dataclass
class OrderSummary:
    """Структура сводки заказов по товару"""
    product_id: int
    title: str
    price: int
    link: str
    total_count: int
    users: List[Dict[str, Any]]  # список пользователей с заказами: {'user_id': int, 'name': str, 'count': int, 'done': bool}
    done: bool = False  # все заказы по этому товару выполнены

# ========== DATA LAYER ==========
def load_data():
    """
    Compatibility snapshot: build an in-memory dict view from tables.
    Other functions should use table-based helpers directly.
    """
    global DATA
    _ensure_db_initialized()

    # Build snapshot fresh each call to avoid stale view
    try:
        users = _tbl(TBL_USERS).all()
        products_list = _tbl(TBL_PRODUCTS).all()
        orders = _tbl(TBL_ORDERS).all()
        old_orders = _tbl(TBL_OLD_ORDERS).all()
        regs = _tbl(TBL_REG).all()
        snapshot = {
            "users": users,
            "collecton": orders,
            "old_collecton": old_orders,
            "collection_open": bool(_meta_get("collection_open", False)),
            "auth_password": _meta_get("auth_password", None),
            # convert products list back to legacy dict shape
            "products": {str(int(product_data.get("product_id", 0))): {
                "product_id": int(product_data.get("product_id", 0)),
                "title": product_data.get("title", ""),
                "price": int(product_data.get("price", 0)),
                "link": product_data.get("link", ""),
            } for product_data in products_list},
            "registration": regs,
        }
        DATA = snapshot
    except Exception:
        logging.exception("Failed to build data snapshot from tables")
        DATA = DATA or {}
    return DATA

 

def save_data(force: bool = False):
    """
    No-op for table-based backend; retained for API compatibility (autosave).
    """
    global DATA_DIRTY
    DATA_DIRTY = False

# Register cleanup function
atexit.register(lambda: save_data(force=True))

# ========== DATA ACCESS WRAPPERS ==========
def get_users() -> list[User]:
    """Получить список всех пользователей."""
    rows = _tbl(TBL_USERS).all()
    return [User.from_record(row) for row in rows] if rows else []

def get_blacklist() -> List[int]:
    """Получить чёрный список пользователей (из registration)."""
    regs = _tbl(TBL_REG).search(Query().blacklisted == True)
    return [int(reg.get("user_id")) for reg in regs]

 

# ===== registration helpers =====

def get_registration_entries() -> List[Registration]:
    """Возвращает список записей регистрации (attempts/blacklisted)."""
    return [Registration.from_record(reg_data) for reg_data in _tbl(TBL_REG).all()]

def get_registration(user_id: int) -> Optional[Registration]:
    for reg in get_registration_entries():
        if reg.user_id == user_id:
            return reg
    return None

def upsert_registration(reg: Registration):
    reg_table = _tbl(TBL_REG)
    query = Query()
    existing = reg_table.get(query.user_id == int(reg.user_id))
    if existing is None:
        reg_table.insert(reg.to_record())
    else:
        reg_table.update(reg.to_record(), query.user_id == int(reg.user_id))

def reg_increment_attempts(user_id: int) -> int:
    reg = get_registration(user_id) or Registration(user_id=user_id)
    reg.attempts += 1
    upsert_registration(reg)
    return reg.attempts

def reg_reset_attempts(user_id: int):
    reg = get_registration(user_id) or Registration(user_id=user_id)
    reg.attempts = 0
    upsert_registration(reg)

def reg_set_blacklisted(user_id: int, value: bool):
    reg = get_registration(user_id) or Registration(user_id=user_id)
    reg.blacklisted = bool(value)
    upsert_registration(reg)

def reg_is_blacklisted(user_id: int) -> bool:
    reg = get_registration(user_id)
    return bool(reg and reg.blacklisted)

# ===== collection state helpers =====

def set_collection_state(state: bool):
    _meta_set("collection_open", bool(state))

def is_collecting() -> bool:
    return bool(_meta_get("collection_open", False))


def move_orders_to_old():
    "Переместить текущие заказы в старые и очистить текущие"""
    current_orders_table = _tbl(TBL_ORDERS)
    old_orders_table = _tbl(TBL_OLD_ORDERS)
    rows = current_orders_table.all()
    if rows:
        old_orders_table.truncate()
        for row in rows:
            old_orders_table.insert(row)
        current_orders_table.truncate()

# ===== user helpers =====

def get_user(user_id: int) -> Optional[User]:
    """Находит запись пользователя по user_id."""
    user_record = _tbl(TBL_USERS).get(Query().user_id == int(user_id))
    return User.from_record(user_record) if user_record else None

def upsert_user(user: User):
    """Сохраняет изменения пользователя в базу данных."""
    users_table = _tbl(TBL_USERS)
    query = Query()
    if users_table.get(query.user_id == int(user.user_id)) is None:
        users_table.insert(user.to_record())
    else:
        users_table.update(user.to_record(), query.user_id == int(user.user_id))

def is_admin(user_id: int) -> bool:
    user = get_user(user_id)
    return bool(user and user.is_admin)

def add_admin(user_id: int):
    user = get_user(user_id)
    if user and not user.is_admin:
        user.is_admin = True
        upsert_user(user)


def del_admin(user_id: int):
    user = get_user(user_id)
    if user and user.is_admin:
        user.is_admin = False
        upsert_user(user)

def set_username(user_id: int, name: str):
    user = get_user(user_id)
    if user:
        if user.name != name:
            user.name = name
            upsert_user(user)

def add_user(user_id: int, name: str):
    if not get_user(user_id):
        new_user = User(user_id=user_id, name=name, is_admin=False)
        upsert_user(new_user)

def get_username(user_id: int) -> Optional[str]:
    user = get_user(user_id)
    return user.name if user else None

def user_exists(user_id: int) -> bool:
    return get_user(user_id) is not None

def remove_user(user_id: int):
    query = Query()
    _tbl(TBL_USERS).remove(query.user_id == int(user_id))
    _tbl(TBL_ORDERS).remove(query.user_id == int(user_id))
    _tbl(TBL_OLD_ORDERS).remove(query.user_id == int(user_id))
    _tbl(TBL_REG).remove(query.user_id == int(user_id))

# ===== order helpers =====

def _orders_table(is_current: bool):
    """Возвращает таблицу заказов для текущих или прошлых заказов."""
    return _tbl(TBL_ORDERS if is_current else TBL_OLD_ORDERS)

def add_user_order(order: UserOrder) -> UserOrder:
    """
    Добавляет заказ пользователю (user_id берётся из order).
    Если запись отсутствует — создаёт её.
    Если у пользователя уже есть такой товар в текущих заказах, увеличивает количество.
    Возвращает добавленный или обновлённый заказ.
    """
    orders_table = _orders_table(True)
    query = Query()
    # Нормализуем типы
    order = UserOrder.from_record(order.to_record())
    existing = orders_table.get((query.user_id == int(order.user_id)) & (query.product_id == int(order.product_id)))
    if existing:
        new_count = int(existing.get("count", 1)) + int(order.count)
        orders_table.update({"count": new_count}, (query.user_id == int(order.user_id)) & (query.product_id == int(order.product_id)))
        existing["count"] = new_count
        return UserOrder.from_record(existing)
    rec = order.to_record()
    orders_table.insert(rec)
    return UserOrder.from_record(rec)

def get_user_orders(user_id: int, is_current: bool) -> List[UserOrder]:
    t = _orders_table(is_current)
    q = Query()
    rows = t.search(q.user_id == int(user_id))
    return [UserOrder.from_record(o) for o in rows]

def get_user_order(user_id: int, product_id: int, is_current: bool) -> Optional[UserOrder]:
    """Возвращает заказ пользователя по product_id или None."""
    orders_table = _orders_table(is_current)
    query = Query()
    rec = orders_table.get((query.user_id == int(user_id)) & (query.product_id == int(product_id)))
    return UserOrder.from_record(rec) if rec else None

def upsert_user_order(order: UserOrder) -> bool:
    """
    Обновляет заказ конкретного пользователя по product_id (user_id берётся из order).
    Возвращает True, если заказ найден и обновлён, иначе False.
    """
    orders_table = _orders_table(True)
    query = Query()
    # Нормализуем типы
    order = UserOrder.from_record(order.to_record())
    if orders_table.get((query.user_id == int(order.user_id)) & (query.product_id == int(order.product_id))) is None:
        return False
    orders_table.update(order.to_record(), (query.user_id == int(order.user_id)) & (query.product_id == int(order.product_id)))
    return True

def remove_user_order(user_id: int, product_id: int, is_current: bool = True) -> bool:
    """
    Удаляет заказ конкретного пользователя по product_id.
    Возвращает True, если заказ найден и удалён.
    """
    orders_table = _orders_table(is_current)
    query = Query()
    removed = orders_table.remove((query.user_id == int(user_id)) & (query.product_id == int(product_id)))
    return bool(removed)

# ===== products helpers =====

def get_product(product_id: int) -> Optional[Product]:
    """Возвращает товар по product_id или None"""
    product_record = _tbl(TBL_PRODUCTS).get(Query().product_id == int(product_id))
    if not product_record:
        return None
    return Product.from_record(product_record)

def upsert_product(product: Product):
    """Создаёт или обновляет товар"""
    products_table = _tbl(TBL_PRODUCTS)
    query = Query()
    doc = product.to_record()
    if products_table.get(query.product_id == int(product.product_id)) is None:
        products_table.insert(doc)
    else:
        products_table.update(doc, query.product_id == int(product.product_id))

def remove_product(product_id: int) -> bool:
    """Удаляет товар из каталога, возвращает True если удалён"""
    products_table = _tbl(TBL_PRODUCTS)
    query = Query()
    removed = products_table.remove(query.product_id == int(product_id))
    return bool(removed)


def get_orders_grouped_by_product() -> Dict[int, List[UserOrder]]:
    """
    Группирует текущие заказы по товарам.
    Возвращает словарь: product_id -> список UserOrder
    """
    current = _tbl(TBL_ORDERS).all()
    grouped: Dict[int, List[UserOrder]] = {}
    for order_record in current:
        product_id = order_record.get("product_id")
        if product_id is None:
            continue
        pid = int(product_id)
        user_order = UserOrder.from_record(order_record)
        if pid not in grouped:
            grouped[pid] = []
        grouped[pid].append(user_order)
    return grouped

def get_orders_grouped_by_user() -> Dict[int, List[UserOrder]]:
    """
    Группирует текущие заказы по пользователям.
    Возвращает словарь: user_id -> список UserOrder
    """
    current = _tbl(TBL_ORDERS).all()
    grouped: Dict[int, List[UserOrder]] = {}
    for order_record in current:
        user_id = order_record.get("user_id")
        if user_id is None:
            continue
        uid = int(user_id)
        user_order = UserOrder.from_record(order_record)
        if uid not in grouped:
            grouped[uid] = []
        grouped[uid].append(user_order)
    return grouped

def mark_product_done_for_all_users(product_id: int) -> int:
    """
    Отмечает все заказы с данным product_id как выполненные для всех пользователей.
    Возвращает количество обновленных заказов.
    """
    orders_table = _orders_table(True)
    query = Query()
    matching = orders_table.search((query.product_id == int(product_id)) & (query.done != True))
    if not matching:
        return 0
    orders_table.update({"done": True}, (query.product_id == int(product_id)) & (query.done != True))
    return len(matching)

def get_orders_total(orders: List[UserOrder]) -> int:
    """Возвращает сумму по списку заказов (UserOrder)."""
    total = 0
    for order in orders:
        product = get_product(order.product_id)
        price = product.price if product else 0
        total += price * order.count
    return total


# ===== password helpers =====

def get_auth_password() -> Optional[str]:
    return _meta_get("auth_password", None)

def set_auth_password(pwd: Optional[str]):
    _meta_set("auth_password", pwd)

# Legacy blacklist/attempts helpers removed (using registration-only model)


def ensure_initial_admin():
    """
    Ensure BOT_OWNER is present as admin
    """
    if BOT_OWNER is not None:
        if not isinstance(BOT_OWNER, list):
            init_list = [BOT_OWNER]
        else:
            init_list = BOT_OWNER
        for admin_id in init_list:
            try:
                uid = int(admin_id)
            except Exception:
                continue
            user = get_user(uid)
            if user:
                if not user.is_admin:
                    user.is_admin = True
                    upsert_user(user)
            else:
                new_user = User(user_id=uid, name="", is_admin=True)
                upsert_user(new_user)