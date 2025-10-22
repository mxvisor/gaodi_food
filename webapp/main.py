import time
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# === Конфигурация ===
CATALOG_URL = "https://www.mealty.ru/catalog/"
CACHE_TTL = 60 * 15  # 15 минут

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# простой in-memory cache
CACHE = {"timestamp": 0, "data": None}


def safe_text(el):
    return el.get_text(strip=True) if el else ""


def _first_url_from_srcset(srcset_value: str, base_url: str = CATALOG_URL) -> str:
    if not srcset_value:
        return ""
    parts = [p.strip() for p in srcset_value.split(",") if p.strip()]
    if not parts:
        return ""
    first = parts[0].split()[0]
    return urljoin(base_url, first)


def _get_img_urls(img_tag, base_url: str = CATALOG_URL):
    """
    Возвращает tuple (img, img_srcset).
    Смотрим в приоритете: data-src, data-fancybox-src, data-srcset, srcset, src
    """
    if img_tag is None:
        return "", ""
    # data-src / fancybox first
    for attr in ("data-src", "data-fancybox-src"):
        val = img_tag.get(attr)
        if val:
            return urljoin(base_url, val), ""
    # data-srcset
    ds = img_tag.get("data-srcset") or img_tag.get("data_srcset")
    if ds:
        first = _first_url_from_srcset(ds, base_url)
        if first:
            return first, ds
    # srcset
    ss = img_tag.get("srcset")
    if ss:
        first = _first_url_from_srcset(ss, base_url)
        if first:
            return first, ss
    # fallback src
    s = img_tag.get("src")
    if s:
        return urljoin(base_url, s), ""
    return "", ""


def fetch_all():
    """
    Сбор категорий и товаров.
    1) Сначала пытаемся собрать меню категорий (ул/ли)
    2) Затем проходим по блокам category-wrapper (если есть), собираем товары внутри и помечаем категорию
    3) Затем проходим по всем .catalog-item (на случай, если что-то не попало)
    """
    try:
        resp = requests.get(CATALOG_URL, timeout=10)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return {"categories": [], "products": []}

    # 1) категории из второго меню (switchable-container)
    categories = []
    categories_map = {}  # id -> name
    # ищем все li в switchable-container
    for li in soup.select(".switchable-container li"):
        cid = li.get("data-category") or li.get("data-id") or li.get("data-category-id")
        name = safe_text(li.select_one("a")) or safe_text(li)
        if cid and name:
            cid = str(cid)
            if cid not in categories_map:
                categories_map[cid] = name
                categories.append({"id": cid, "name": name})

    # Дополнительно: если на странице есть category-wrapper с заголовком — возьмём их порядок/имена
    # (они могут содержать human-readable titles)
    for wrapper in soup.select(".category-wrapper"):
        cid = wrapper.get("data-category") or wrapper.get("data-category-id")
        title_el = wrapper.select_one(".menu-category-title span") or wrapper.select_one("h3")
        name = safe_text(title_el) if title_el else None
        if cid:
            cid = str(cid)
            if cid not in categories_map:
                if name:
                    categories_map[cid] = name
                    categories.append({"id": cid, "name": name})
                else:
                    # добавим placeholder если не было
                    categories_map[cid] = f"Категория {cid}"
                    categories.append({"id": cid, "name": categories_map[cid]})

    # 2) товары: проход по category-wrapper (гарантирует связь категория->товары)
    products = []
    seen_product_category_pairs = set()  # (product_key, category_id) для избежания дублей в одной категории
    seen_global_ids = set()  # для отслеживания обработанных товаров глобально

    for wrapper in soup.select(".category-wrapper"):
        wrapper_cid = wrapper.get("data-category") or wrapper.get("data-category-id") or wrapper.get("data-category-id")
        if wrapper_cid:
            wrapper_cid = str(wrapper_cid)
        # попробуем заголовок для случая отсутствия в categories_map
        if wrapper_cid and wrapper_cid not in categories_map:
            title_el = wrapper.select_one(".menu-category-title span") or wrapper.select_one("h3")
            categories_map[wrapper_cid] = safe_text(title_el) or f"Категория {wrapper_cid}"
            categories.append({"id": wrapper_cid, "name": categories_map[wrapper_cid]})

        for item in wrapper.select(".catalog-item"):
            p = parse_card(item, wrapper_cid)
            if p and (p["seller_id"] or p["product_id"]):
                key = (p["seller_id"] or p["product_id"])
                category_key = (key, p["category_id"])
                
                # Добавляем товар в каждую категорию отдельно, но только если не дубль в этой категории
                if category_key not in seen_product_category_pairs:
                    products.append(p)
                    seen_product_category_pairs.add(category_key)
                    seen_global_ids.add(key)

    # 3) запасной проход — все .catalog-item (на случай карточек вне wrapper)
    for item in soup.select(".catalog-item"):
        p = parse_card(item, None)
        key = (p["seller_id"] or p["product_id"]) if p else None
        if not p or not key:
            continue
        category_key = (key, p["category_id"])
        
        # Добавляем только если товар не был обработан в этой категории
        if category_key not in seen_product_category_pairs:
            products.append(p)
            seen_product_category_pairs.add(category_key)
            seen_global_ids.add(key)
            # если категория появилась и ещё не в categories_map — добавим
            cid = str(p.get("category_id") or "other")
            if cid not in categories_map:
                categories_map[cid] = f"Категория {cid}"
                categories.append({"id": cid, "name": categories_map[cid]})

    # итог: если мы не собрали категории из меню, но получили map из карточек — заполним список
    if not categories and categories_map:
        for cid, name in categories_map.items():
            categories.append({"id": cid, "name": name})

    return {"categories": categories, "products": products}


def parse_card(item, forced_category=None):
    """
    Парсинг одной карточки (BeautifulSoup element).
    Возвращает словарь с полями: product_id, seller_id, category_id, title, subtitle, desc, price, img, img_srcset, link, is_new, out_of_stock, is_hidden
    """
    try:
        product_id = item.get("data-product_id") or item.get("data-product-id") or item.get("data-id")
        seller_id = item.get("data-seller-product_id") or item.get("data-seller-product-id") or item.get("data-seller-id")
        # category_id может быть на карточке или на img[data-category-id]
        category_id = item.get("data-category-id") or item.get("data-category") or ""
        
        # detect is_hidden: presence of 'hidden' class
        classes = item.get("class") or []
        is_hidden = "hidden" in classes
        title_el = item.select_one(".meal-card__name") or item.select_one(".catalog__title") or item.select_one("h3")
        subtitle_el = item.select_one(".meal-card__name-note") or item.select_one(".subtitle")
        desc_el = item.select_one(".meal-card__description") or item.select_one(".description")
        price_el = item.select_one(".basket__footer-total-count") or item.select_one(".meal-card__price") or item.select_one(".price")

        # find image candidates (there can be a "newpl" badge img before main img)
        img_candidates = item.select(".meal-card__image img, .meal-card__image > img, img")
        img_tag = None
        for it in img_candidates:
            # choose candidate that has data-src / data-srcset / data-fancybox-src or data-category-id
            if it.get("data-src") or it.get("data-srcset") or it.get("data-fancybox-src") or it.get("data-category-id"):
                img_tag = it
                break
        if not img_tag and img_candidates:
            img_tag = img_candidates[-1]

        # detect is_new if there is an img.newpl inside meal-card__image
        is_new = bool(item.select_one(".meal-card__image img.newpl") or item.select_one("img.newpl"))

        # detect out_of_stock: presence of .out-of-stock-show and not hidden
        out_el = item.select_one(".out-of-stock-show")
        out_of_stock = False
        if out_el:
            classes = out_el.get("class") or []
            # if it doesn't have 'hidden' class and has text -> sold out
            if "hidden" not in classes and safe_text(out_el):
                out_of_stock = True

        # if image tag has data-category-id override
        if img_tag and img_tag.get("data-category-id"):
            category_id = category_id or img_tag.get("data-category-id")

        img, img_srcset = _get_img_urls(img_tag) if img_tag is not None else ("", "")

        product = {
            "product_id": product_id,
            "seller_id": seller_id,
            "category_id": (forced_category or category_id or "other"),
            "title": safe_text(title_el),
            "subtitle": safe_text(subtitle_el),
            "desc": safe_text(desc_el),
            "price": (price_el.get_text(strip=True) if price_el else "") or "",
            "img": img or "",
            "img_srcset": img_srcset or "",
#            "link": (f"https://www.mealty.ru/#sproduct_{seller_id}" if seller_id else ""),
            "is_new": is_new,
            "out_of_stock": out_of_stock,
            "is_hidden": is_hidden
        }
        return product
    except Exception:
        return None


def get_cached():
    now = time.time()
    if CACHE["data"] is None or (now - CACHE["timestamp"] > CACHE_TTL):
        CACHE["data"] = fetch_all()
        CACHE["timestamp"] = now
    return CACHE["data"]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, category: str = None):
    data = get_cached()
    products = data.get("products", [])
    # убираем распроданные и скрытые товары
    products = [p for p in products if not p.get("out_of_stock") and not p.get("is_hidden")]

    # Собираем категории, где есть хотя бы один не out-of-stock и не hidden товар
    visible_category_ids = set(p["category_id"] for p in products)
    categories = [c for c in data.get("categories", []) if c["id"] in visible_category_ids]

    # фильтрация по категории (если передана)
    if category:
        products = [p for p in products if str(p.get("category_id")) == str(category)]

    return templates.TemplateResponse("index.html", {"request": request, "categories": categories, "products": products})
