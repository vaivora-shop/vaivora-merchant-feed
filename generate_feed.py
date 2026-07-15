#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from lxml import etree

SITEMAP_URL = "https://vaivora.shop/sitemap.xml"
SHOP_URL = "https://vaivora.shop/"
OUTPUT_FILE = Path("public/products.xml")
REPORT_FILE = Path("feed-report.json")
GOOGLE_NS = "http://base.google.com/ns/1.0"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; VaivoraMerchantFeed/1.0; +https://vaivora.shop/)",
    "Accept-Language": "lt-LT,lt;q=0.9,en;q=0.7",
}


@dataclass
class Product:
    id: str
    title: str
    description: str
    link: str
    image_link: str
    price: str
    availability: str
    condition: str = "new"
    brand: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    additional_images: list[str] = field(default_factory=list)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(clean_text(v) for v in value if v is not None).strip()
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("@value"))
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def clean_description(value: Any, fallback: str) -> str:
    result = clean_text(value) or fallback
    result = BeautifulSoup(result, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", result).strip()[:5000]


def normalize_price(value: Any, currency: str = "EUR") -> str | None:
    raw = clean_text(value).replace("\xa0", " ").replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        amount = Decimal(match.group(0)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return f"{amount} {currency.upper()}"


def normalize_availability(value: Any) -> str:
    raw = clean_text(value).lower().rstrip("/").split("/")[-1]
    key = raw.replace("-", "").replace("_", "").replace(" ", "")
    return {
        "instock": "in_stock",
        "limitedavailability": "in_stock",
        "outofstock": "out_of_stock",
        "soldout": "out_of_stock",
        "preorder": "preorder",
        "backorder": "backorder",
    }.get(key, "in_stock")


def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def is_product(node: dict[str, Any]) -> bool:
    kind = node.get("@type")
    if isinstance(kind, list):
        return any(str(item).lower() == "product" for item in kind)
    return str(kind).lower() == "product"


def first_offer(node: dict[str, Any]) -> dict[str, Any]:
    offers = node.get("offers") or {}
    if isinstance(offers, list):
        offers = next((item for item in offers if isinstance(item, dict)), {})
    if not isinstance(offers, dict):
        return {}
    nested = offers.get("offers")
    if isinstance(nested, list):
        return next((item for item in nested if isinstance(item, dict)), offers)
    return offers


def product_images(node: dict[str, Any], page_url: str) -> tuple[str, list[str]]:
    raw = node.get("image")
    values: list[str] = []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, dict):
        values = [clean_text(raw.get("url") or raw.get("contentUrl"))]
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                values.append(clean_text(item.get("url") or item.get("contentUrl")))
    values = [urljoin(page_url, value) for value in values if value]
    values = list(dict.fromkeys(values))
    return (values[0] if values else "", values[1:11])


def meta_value(soup: BeautifulSoup, attribute: str, value: str) -> str:
    tag = soup.find("meta", attrs={attribute: value})
    return clean_text(tag.get("content")) if tag else ""


def make_product_id(node: dict[str, Any], url: str) -> str:
    value = clean_text(
        node.get("sku")
        or node.get("productID")
        or node.get("mpn")
        or node.get("gtin14")
        or node.get("gtin13")
        or node.get("gtin12")
        or node.get("gtin8")
    )
    if value:
        return value[:50]
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    return (slug or hashlib.sha1(url.encode("utf-8")).hexdigest())[:50]


def extract_product(page_url: str, page_html: str) -> Product | None:
    soup = BeautifulSoup(page_html, "html.parser")
    canonical_tag = soup.find("link", rel="canonical")
    canonical = urljoin(page_url, canonical_tag.get("href")) if canonical_tag else page_url

    product_nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", type=lambda value: value and "ld+json" in value):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        product_nodes.extend(node for node in walk_json(data) if is_product(node))

    if product_nodes:
        node = product_nodes[0]
        offer = first_offer(node)

        title = clean_text(node.get("name"))
        description = clean_description(
            node.get("description"),
            meta_value(soup, "name", "description") or title,
        )
        image_link, additional_images = product_images(node, canonical)
        if not image_link:
            image_link = urljoin(canonical, meta_value(soup, "property", "og:image"))

        currency = clean_text(offer.get("priceCurrency") or node.get("priceCurrency") or "EUR")
        product_price = normalize_price(
            offer.get("price") or offer.get("lowPrice") or node.get("price"),
            currency,
        )
        product_availability = normalize_availability(
            offer.get("availability") or node.get("availability")
        )

        brand = clean_text(node.get("brand")) or None
        gtin = clean_text(
            node.get("gtin")
            or node.get("gtin14")
            or node.get("gtin13")
            or node.get("gtin12")
            or node.get("gtin8")
        ) or None
        mpn = clean_text(node.get("mpn")) or None

        if title and image_link and product_price:
            return Product(
                id=make_product_id(node, canonical),
                title=title[:150],
                description=description,
                link=canonical,
                image_link=image_link,
                additional_images=additional_images,
                price=product_price,
                availability=product_availability,
                brand=brand,
                gtin=gtin,
                mpn=mpn,
            )

    # Atsarginis variantas, jeigu JSON-LD nėra.
    title = meta_value(soup, "property", "og:title")
    image_link = meta_value(soup, "property", "og:image")
    amount = (
        meta_value(soup, "property", "product:price:amount")
        or meta_value(soup, "property", "og:price:amount")
    )
    currency = meta_value(soup, "property", "product:price:currency") or "EUR"
    product_price = normalize_price(amount, currency)

    if title and image_link and product_price:
        return Product(
            id=make_product_id({}, canonical),
            title=title[:150],
            description=clean_description(
                meta_value(soup, "property", "og:description"),
                title,
            ),
            link=canonical,
            image_link=urljoin(canonical, image_link),
            price=product_price,
            availability="in_stock",
        )
    return None


def read_sitemap(session: requests.Session, sitemap_url: str, seen: set[str] | None = None) -> list[str]:
    seen = seen or set()
    if sitemap_url in seen:
        return []
    seen.add(sitemap_url)

    logging.info("Skaitomas sitemap: %s", sitemap_url)
    response = session.get(sitemap_url, timeout=30)
    response.raise_for_status()
    root = etree.fromstring(response.content)
    locations = [
        clean_text(element.text)
        for element in root.xpath("//*[local-name()='loc']")
        if clean_text(element.text)
    ]

    if etree.QName(root).localname.lower() == "sitemapindex":
        urls: list[str] = []
        for child in locations:
            urls.extend(read_sitemap(session, child, seen))
        return urls
    return locations


def add_google_field(item: etree._Element, name: str, value: str | None) -> None:
    if value:
        etree.SubElement(item, f"{{{GOOGLE_NS}}}{name}").text = value


def write_feed(products: list[Product]) -> None:
    rss = etree.Element("rss", nsmap={"g": GOOGLE_NS}, version="2.0")
    channel = etree.SubElement(rss, "channel")
    etree.SubElement(channel, "title").text = "Vaivora.shop produktai"
    etree.SubElement(channel, "link").text = SHOP_URL
    etree.SubElement(channel, "description").text = "Google Merchant produktų srautas"

    for product in products:
        item = etree.SubElement(channel, "item")
        add_google_field(item, "id", product.id)
        etree.SubElement(item, "title").text = product.title
        etree.SubElement(item, "description").text = product.description
        etree.SubElement(item, "link").text = product.link
        add_google_field(item, "image_link", product.image_link)
        for image in product.additional_images:
            add_google_field(item, "additional_image_link", image)
        add_google_field(item, "availability", product.availability)
        add_google_field(item, "price", product.price)
        add_google_field(item, "condition", product.condition)
        add_google_field(item, "brand", product.brand)
        add_google_field(item, "gtin", product.gtin)
        add_google_field(item, "mpn", product.mpn)
        if not any((product.brand, product.gtin, product.mpn)):
            add_google_field(item, "identifier_exists", "no")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    etree.ElementTree(rss).write(
        str(OUTPUT_FILE),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = requests.Session()
    session.headers.update(HEADERS)

    page_urls = list(dict.fromkeys(read_sitemap(session, SITEMAP_URL)))
    logging.info("Sitemap URL kiekis: %d", len(page_urls))

    products: list[Product] = []
    failures: list[str] = []

    for index, url in enumerate(page_urls, start=1):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            product = extract_product(response.url, response.text)
            if product:
                products.append(product)
                logging.info("[%d/%d] PREKĖ: %s", index, len(page_urls), product.title)
        except Exception as exc:
            failures.append(url)
            logging.warning("[%d/%d] Klaida %s: %s", index, len(page_urls), url, exc)
        time.sleep(0.20)

    unique: dict[str, Product] = {}
    for product in products:
        unique.setdefault(product.id, product)
    products = list(unique.values())

    write_feed(products)
    REPORT_FILE.write_text(
        json.dumps(
            {
                "sitemap_urls": len(page_urls),
                "products_written": len(products),
                "failed_urls": failures,
                "output": str(OUTPUT_FILE),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logging.info("Baigta: %d prekių -> %s", len(products), OUTPUT_FILE)
    if not products:
        logging.error("Nerasta nė viena prekė.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
