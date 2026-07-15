#!/usr/bin/env python3
"""
Google Merchant XML feed generator for Hostinger Website Builder stores.

How it works:
1. Reads every URL from sitemap.xml (including nested sitemap indexes).
2. Opens each page.
3. Finds schema.org Product + Offer data in JSON-LD.
4. Generates an RSS 2.0 Google Merchant feed.

The script does not invent GTIN, MPN, brand, price or stock information.
"""

from __future__ import annotations

import argparse
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

GOOGLE_NS = "http://base.google.com/ns/1.0"
NSMAP = {"g": GOOGLE_NS}
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; VaivoraMerchantFeed/1.0; "
        "+https://vaivora.shop/)"
    ),
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


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(text(v) for v in value if v is not None).strip()
    if isinstance(value, dict):
        return text(value.get("name") or value.get("@value"))
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def clean_description(value: Any, fallback: str) -> str:
    value = text(value) or fallback
    value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:5000]


def normalize_price(value: Any, currency: str = "EUR") -> str | None:
    raw = text(value).replace("\xa0", " ").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        amount = Decimal(match.group(0))
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    return f"{amount.quantize(Decimal('0.01'))} {currency.upper()}"


def normalize_availability(value: Any) -> str:
    raw = text(value).lower()
    mapping = {
        "instock": "in_stock",
        "in_stock": "in_stock",
        "limitedavailability": "in_stock",
        "outofstock": "out_of_stock",
        "out_of_stock": "out_of_stock",
        "soldout": "out_of_stock",
        "preorder": "preorder",
        "pre_order": "preorder",
        "backorder": "backorder",
        "back_order": "backorder",
    }
    tail = raw.rstrip("/").split("/")[-1].replace("-", "").replace(" ", "")
    return mapping.get(tail, "in_stock")


def product_id(node: dict[str, Any], url: str) -> str:
    candidate = text(
        node.get("sku")
        or node.get("productID")
        or node.get("mpn")
        or node.get("gtin13")
        or node.get("gtin14")
        or node.get("gtin12")
        or node.get("gtin8")
    )
    if candidate:
        return candidate[:50]
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    if slug:
        return slug[:50]
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:40]


def iter_jsonld_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "@graph" in value:
            yield from iter_jsonld_objects(value["@graph"])
        yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from iter_jsonld_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_jsonld_objects(child)


def is_product(node: dict[str, Any]) -> bool:
    kind = node.get("@type")
    if isinstance(kind, list):
        return any(str(x).lower() == "product" for x in kind)
    return str(kind).lower() == "product"


def get_offer(node: dict[str, Any]) -> dict[str, Any]:
    offers = node.get("offers") or {}
    if isinstance(offers, list):
        offers = next((o for o in offers if isinstance(o, dict)), {})
    if not isinstance(offers, dict):
        return {}
    if str(offers.get("@type", "")).lower() == "aggregateoffer":
        nested = offers.get("offers")
        if isinstance(nested, list):
            return next((o for o in nested if isinstance(o, dict)), offers)
    return offers


def absolutize(url: str, page_url: str) -> str:
    return urljoin(page_url, text(url))


def first_image(node: dict[str, Any], page_url: str) -> tuple[str, list[str]]:
    raw = node.get("image")
    images: list[str] = []
    if isinstance(raw, str):
        images = [raw]
    elif isinstance(raw, dict):
        images = [text(raw.get("url") or raw.get("contentUrl"))]
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                images.append(item)
            elif isinstance(item, dict):
                images.append(text(item.get("url") or item.get("contentUrl")))
    images = [absolutize(x, page_url) for x in images if x]
    unique = list(dict.fromkeys(images))
    return (unique[0] if unique else "", unique[1:11])


def meta_content(soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None) -> str:
    attrs = {"property": prop} if prop else {"name": name}
    tag = soup.find("meta", attrs=attrs)
    return text(tag.get("content")) if tag else ""


def extract_product(page_url: str, page_html: str) -> Product | None:
    soup = BeautifulSoup(page_html, "html.parser")
    canonical_tag = soup.find("link", rel="canonical")
    canonical = absolutize(canonical_tag.get("href"), page_url) if canonical_tag else page_url

    product_nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", type=lambda x: x and "ld+json" in x):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        product_nodes.extend(node for node in iter_jsonld_objects(data) if is_product(node))

    if product_nodes:
        node = product_nodes[0]
        offer = get_offer(node)

        title = text(node.get("name"))
        description = clean_description(
            node.get("description"),
            meta_content(soup, name="description") or title,
        )
        image_link, additional_images = first_image(node, canonical)
        if not image_link:
            image_link = absolutize(meta_content(soup, prop="og:image"), canonical)

        currency = text(
            offer.get("priceCurrency")
            or node.get("priceCurrency")
            or "EUR"
        )
        price_value = (
            offer.get("price")
            or offer.get("lowPrice")
            or node.get("price")
        )
        price = normalize_price(price_value, currency)

        availability = normalize_availability(
            offer.get("availability") or node.get("availability")
        )

        brand = text(node.get("brand")) or None
        gtin = text(
            node.get("gtin")
            or node.get("gtin14")
            or node.get("gtin13")
            or node.get("gtin12")
            or node.get("gtin8")
        ) or None
        mpn = text(node.get("mpn")) or None

        if title and image_link and price:
            return Product(
                id=product_id(node, canonical),
                title=title[:150],
                description=description,
                link=canonical,
                image_link=image_link,
                additional_images=additional_images,
                price=price,
                availability=availability,
                brand=brand,
                gtin=gtin,
                mpn=mpn,
            )

    # Conservative fallback using Open Graph.
    # A page is accepted only when it has a product price and image.
    title = meta_content(soup, prop="og:title")
    image_link = meta_content(soup, prop="og:image")
    price_amount = (
        meta_content(soup, prop="product:price:amount")
        or meta_content(soup, prop="og:price:amount")
    )
    currency = (
        meta_content(soup, prop="product:price:currency")
        or meta_content(soup, prop="og:price:currency")
        or "EUR"
    )
    price = normalize_price(price_amount, currency)
    if title and image_link and price:
        description = clean_description(
            meta_content(soup, prop="og:description"),
            meta_content(soup, name="description") or title,
        )
        return Product(
            id=product_id({}, canonical),
            title=title[:150],
            description=description,
            link=canonical,
            image_link=absolutize(image_link, canonical),
            price=price,
            availability="in_stock",
        )
    return None


def parse_sitemap(session: requests.Session, sitemap_url: str, timeout: int) -> list[str]:
    seen_sitemaps: set[str] = set()
    page_urls: list[str] = []

    def walk(url: str) -> None:
        if url in seen_sitemaps:
            return
        seen_sitemaps.add(url)
        logging.info("Reading sitemap: %s", url)
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        root = etree.fromstring(response.content)
        local_name = etree.QName(root).localname.lower()

        locations = [
            text(element.text)
            for element in root.xpath("//*[local-name()='loc']")
            if text(element.text)
        ]
        if local_name == "sitemapindex":
            for child_url in locations:
                walk(child_url)
        else:
            page_urls.extend(locations)

    walk(sitemap_url)
    return list(dict.fromkeys(page_urls))


def add_g(item: etree._Element, name: str, value: str | None) -> None:
    if value:
        etree.SubElement(item, f"{{{GOOGLE_NS}}}{name}").text = value


def write_feed(products: list[Product], output: Path, shop_url: str) -> None:
    rss = etree.Element("rss", nsmap=NSMAP, version="2.0")
    channel = etree.SubElement(rss, "channel")
    etree.SubElement(channel, "title").text = "Vaivora.shop produktai"
    etree.SubElement(channel, "link").text = shop_url
    etree.SubElement(channel, "description").text = "Google Merchant produktų srautas"

    for product in products:
        item = etree.SubElement(channel, "item")
        add_g(item, "id", product.id)
        etree.SubElement(item, "title").text = product.title
        etree.SubElement(item, "description").text = product.description
        etree.SubElement(item, "link").text = product.link
        add_g(item, "image_link", product.image_link)
        for extra in product.additional_images:
            add_g(item, "additional_image_link", extra)
        add_g(item, "availability", product.availability)
        add_g(item, "price", product.price)
        add_g(item, "condition", product.condition)
        add_g(item, "brand", product.brand)
        add_g(item, "gtin", product.gtin)
        add_g(item, "mpn", product.mpn)

        # Do not pretend identifiers are absent when brand/GTIN/MPN exists.
        if not any((product.brand, product.gtin, product.mpn)):
            add_g(item, "identifier_exists", "no")

    output.parent.mkdir(parents=True, exist_ok=True)
    tree = etree.ElementTree(rss)
    tree.write(
        str(output),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sitemap", default="https://vaivora.shop/sitemap.xml")
    parser.add_argument("--shop-url", default="https://vaivora.shop/")
    parser.add_argument("--output", default="public/products.xml")
    parser.add_argument("--delay", type=float, default=0.20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    urls = parse_sitemap(session, args.sitemap, args.timeout)
    if args.limit:
        urls = urls[: args.limit]
    logging.info("Sitemap URLs: %d", len(urls))

    products: list[Product] = []
    failures: list[str] = []
    for index, url in enumerate(urls, start=1):
        try:
            response = session.get(url, timeout=args.timeout)
            response.raise_for_status()
            product = extract_product(response.url, response.text)
            if product:
                products.append(product)
                logging.info("[%d/%d] PRODUCT: %s", index, len(urls), product.title)
            else:
                logging.debug("[%d/%d] Not a product: %s", index, len(urls), url)
        except Exception as exc:
            logging.warning("[%d/%d] Failed %s: %s", index, len(urls), url, exc)
            failures.append(url)
        time.sleep(max(0, args.delay))

    # Keep the first occurrence of each ID.
    unique: dict[str, Product] = {}
    for product in products:
        unique.setdefault(product.id, product)
    products = list(unique.values())

    output = Path(args.output)
    write_feed(products, output, args.shop_url)

    report = {
        "sitemap_urls": len(urls),
        "products_written": len(products),
        "failed_urls": failures,
        "output": str(output),
    }
    Path("feed-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logging.info("Finished: %d products -> %s", len(products), output)

    if not products:
        logging.error("No products were found. Inspect page structured data or run with --verbose.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
