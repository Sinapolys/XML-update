#!/usr/bin/env python3
"""
Скачивает фиды нескольких поставщиков (YML/XML), для КАЖДОГО поставщика применяет
его собственные фильтры и наценку и склеивает всё в один итоговый файл.

Для каждого поставщика настраивается отдельно (см. блоки настроек ниже и список SUPPLIERS):
  - исключаемые категории (с подкатегориями) и слова в названии товара;
  - исключение товаров с нулевым остатком и (опционально) с available="false";
  - наценка на все товары и отдельная наценка на выбранные категории.
У оставшихся офферов убираются скидки: price <- oldprice, тег oldprice удаляется.
В конце подмешиваются собственные товары из custom_offers.xml (без наценки и фильтров).
"""

import os
import re
import sys
import time
import urllib.request

OUTPUT_PATH = "output/filtered_feed.xml"

# Файл со своими собственными товарами (не от поставщика).
# Лежит в репозитории рядом со скриптом, заполняется вручную —
# см. custom_offers_template.xml. Если файла нет — просто пропускается.
CUSTOM_OFFERS_PATH = "custom_offers.xml"

# ГЛАВНЫЙ ПЕРЕКЛЮЧАТЕЛЬ НАЦЕНКИ (для всех поставщиков сразу)
# True  -> цены поднимаются на наценку поставщика и округляются до ROUND_STEP
# False -> наценка и округление ВЫКЛЮЧЕНЫ, в фид идут оригинальные цены поставщиков
#          (кроме снятия скидки: price всё равно берётся из oldprice, если она была)
ENABLE_MARKUP = True

# До какого шага округлять итоговую цену (5 -> ...0/...5, 10 -> ...0, 1 -> обычное целое)
ROUND_STEP = 1


# =====================================================================
# ПОСТАВЩИК 1: knigovan.com (книги)
# =====================================================================
SOURCE_URL = "https://knigovan.com/price/exportPrice.xml"

EXCLUDED_CATEGORIES = {
    "130", "131", "134", "105", "120", "96", "97", "98", "99", "100",
    "101", "152", "168", "158", "159", "160", "161", "163", "162", "153",
    "155", "156", "154", "157", "169", "164", "165", "166", "167", "77",
    "89", "82", "83", "84", "85", "86", "87", "88", "78", "79",
    "80", "81", "146", "148", "151", "147", "149", "150", "36", "170",
    "172", "171", "173", "174", "175", "176", "177", "178", "60", "61",
    "68", "69",
}

# Ключові слова в назві товару (без урахування регістру), при наявності яких
# оффер виключається повністю — незалежно від його categoryId.
# Атласи у постачальника фактично лежать впереміш зі звичайними
# робочими зошитами й посібниками (category id 9-11, 47-53 тощо),
# тому фільтр по категорії "Атласи" (id 12/54) не спрацьовує —
# треба виключати по назві.
EXCLUDED_NAME_KEYWORDS = [

]

# Наценка на ВСЕ товары этого поставщика (в долях, 0.10 = +10%).
# 0 -> товары без особой категории идут по оригинальной цене поставщика.
MARKUP_DEFAULT = 0

# ОТДЕЛЬНАЯ наценка для отдельных категорий: {"ID категории": наценка}.
# Перекрывает MARKUP_DEFAULT. Достаточно указать ID родительской категории —
# подкатегории входят автоматически; если у подкатегории указана своя наценка,
# она главнее родительской.
# "17" и "62" — это «Підручники» (1-4 клас и 5-11 клас).
MARKUP_BY_CATEGORY = {
    "17": 0.12,
    "62": 0.12,
}


# =====================================================================
# ПОСТАВЩИК 2: Tenzi (бытовая и автохимия)
# Ссылка h2group.com.ua перенаправляет на tenzi.ua — скрипт идёт по редиректу сам.
# ID категорий у него — UUID-строки (например "7b06c2b0-6adb-44df-af04-ab190cf06c6a").
# Список категорий можно посмотреть в самом фиде: <category id="..." parentId="...">Название</category>
# =====================================================================
TENZI_URL = "https://h2group.com.ua/price-list/prom.xml"

# Исключаемые категории (с подкатегориями), например {"bc90f889-ad03-4d3e-b26c-34fac15e17e1"}.
# Пустое множество -> берём все категории.
TENZI_EXCLUDED_CATEGORIES = set()

# Слова в названии товара, при наличии которых товар исключается (без учёта регистра)
TENZI_EXCLUDED_NAME_KEYWORDS = []

# Исключать товары с available="false" (у этого поставщика их ~четверть,
# при этом quantity_in_stock у них не нулевой, поэтому фильтр по остатку их не ловит)
TENZI_SKIP_UNAVAILABLE = True

# Наценка на все товары и по категориям. 0 -> цены как в исходном фиде Tenzi, без наценки и округления.
TENZI_MARKUP_DEFAULT = 0
TENZI_MARKUP_BY_CATEGORY = {}


# =====================================================================
# СПИСОК ПОСТАВЩИКОВ. Первый успешно скачанный становится «основой» итогового
# файла (его шапка, валюты), товары и категории остальных добавляются в него.
#   required: True  -> если фид не скачался/пустой, скрипт падает с ошибкой, а старый
#                      итоговый файл в репозитории остаётся нетронутым (рекомендуется);
#             False -> такой поставщик при сбое пропускается, остальные обновятся.
#   min_size: минимальный размер ответа в байтах; меньше — считаем заглушкой и пробуем снова.
# =====================================================================
SUPPLIERS = [
    {
        "name": "knigovan",
        "url": SOURCE_URL,
        "min_size": 1_000_000,
        "required": True,
        "excluded_categories": EXCLUDED_CATEGORIES,
        "excluded_name_keywords": EXCLUDED_NAME_KEYWORDS,
        "skip_unavailable": False,
        "markup_default": MARKUP_DEFAULT,
        "markup_by_category": MARKUP_BY_CATEGORY,
    },
    {
        "name": "tenzi",
        "url": TENZI_URL,
        "min_size": 50_000,
        "required": True,
        "excluded_categories": TENZI_EXCLUDED_CATEGORIES,
        "excluded_name_keywords": TENZI_EXCLUDED_NAME_KEYWORDS,
        "skip_unavailable": TENZI_SKIP_UNAVAILABLE,
        "markup_default": TENZI_MARKUP_DEFAULT,
        "markup_by_category": TENZI_MARKUP_BY_CATEGORY,
    },
]


def apply_markup(price_value: float, rate: float = None) -> int:
    """Поднимает цену на rate (по умолчанию MARKUP_DEFAULT) и округляет вверх
    до ближайного ROUND_STEP, чтобы получилось "красивое" число
    (например, оканчивающееся на 0 или 5)."""
    import math
    if rate is None:
        rate = MARKUP_DEFAULT
    # round(..., 6) убирает погрешность float (100 * 1.1 = 110.00000000000001),
    # из-за которой ceil иногда округлял бы на целый шаг больше
    raw = round(price_value * (1 + rate), 6)
    if ROUND_STEP <= 1:
        return int(math.ceil(raw))
    return int(math.ceil(raw / ROUND_STEP) * ROUND_STEP)


def fetch_source(url: str, min_size: int = 1_000_000, attempts: int = 4, delay_seconds: int = 8) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "no-cache",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
    }

    last_content = ""
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:  # редиректы urllib обрабатывает сам
            last_content = resp.read().decode("utf-8", errors="replace")

        if "One moment, please" in last_content or "Хвилинку" in last_content or len(last_content) < min_size:
            print(
                f"Попытка {attempt}/{attempts}: получена заглушка/маленький ответ "
                f"({len(last_content)} байт). Жду {delay_seconds} сек. и пробую снова..."
            )
            if attempt < attempts:
                time.sleep(delay_seconds)
                continue
        else:
            return last_content

    return last_content


def parse_categories(content: str):
    """Возвращает {id категории: id родителя или None}. ID могут быть и числами,
    и строками (UUID) — атрибуты читаются в любом порядке."""
    parent_of = {}
    for m in re.finditer(r"<category\b([^>]*)>", content):
        attrs = m.group(1)
        idm = re.search(r'\bid="([^"]+)"', attrs)
        if not idm:
            continue
        pm = re.search(r'\bparentId="([^"]+)"', attrs)
        parent_of[idm.group(1)] = pm.group(1) if pm else None
    return parent_of


def build_is_excluded(parent_of: dict, excluded_roots: set):
    cache = {}

    def is_excluded(cid: str) -> bool:
        if cid in cache:
            return cache[cid]
        cur = cid
        seen = set()
        result = False
        while cur is not None and cur not in seen:
            seen.add(cur)
            if cur in excluded_roots:
                result = True
                break
            cur = parent_of.get(cur)
        cache[cid] = result
        return result

    return is_excluded


def build_get_markup(parent_of: dict, markup_default: float, markup_by_category: dict):
    """Возвращает функцию get_markup(categoryId) -> (наценка, из_категории).
    Идёт от категории вверх по родителям и берёт первую найденную в
    markup_by_category; если не нашла — markup_default."""
    cache = {}

    def get_markup(cid: str):
        if cid in cache:
            return cache[cid]
        cur = cid
        seen = set()
        result = (markup_default, False)
        while cur is not None and cur not in seen:
            seen.add(cur)
            if cur in markup_by_category:
                result = (markup_by_category[cur], True)
                break
            cur = parent_of.get(cur)
        cache[cid] = result
        return result

    return get_markup


def filter_offers(content: str, supplier: dict, parent_of: dict):
    """Применяет к фиду ОДНОГО поставщика его фильтры и наценку.

    Удаляет блоки <offer>...</offer>:
      1) чьё название содержит слово из excluded_name_keywords;
      2) чья категория (или её родитель) входит в excluded_categories;
      3) с available="false" (если skip_unavailable);
      4) с нулевым остатком quantity_in_stock=0;
      5) с некорректной ценой (0 или нет цены).
    У оставшихся убирает скидку (price <- oldprice) и применяет наценку.
    Теги могут содержать переносы строк и пробелы внутри — это учтено.
    Возвращает (новый_content, stats), где stats — словарь со счётчиками.
    """
    offer_pattern = re.compile(r"<offer\b.*?</offer>", re.DOTALL)
    name_pattern = re.compile(r"<name>\s*([^<]*?)\s*</name>")
    price_pattern = re.compile(r"<price>\s*(\d+(?:\.\d+)?)\s*</price>")
    oldprice_pattern = re.compile(r"<oldprice>\s*(\d+(?:\.\d+)?)\s*</oldprice>")
    cat_pattern = re.compile(r"<categoryId>\s*([^<\s]+)\s*</categoryId>")
    qty_pattern = re.compile(r"<quantity_in_stock>\s*(\d+)\s*</quantity_in_stock>")
    avail_pattern = re.compile(r'<offer\b[^>]*\bavailable="([^"]*)"')

    is_excluded = build_is_excluded(parent_of, supplier["excluded_categories"])
    get_markup = build_get_markup(parent_of, supplier["markup_default"], supplier["markup_by_category"])
    name_keywords_lower = [kw.lower() for kw in supplier["excluded_name_keywords"]]
    skip_unavailable = supplier.get("skip_unavailable", False)

    stats = {
        "kept": 0, "removed_name": 0, "removed_category": 0, "removed_unavailable": 0,
        "removed_no_stock": 0, "removed_invalid_price": 0, "discounts_removed": 0,
        "markup_applied": 0, "markup_special": 0,
    }

    def repl(match: re.Match) -> str:
        block = match.group(0)

        # 1. Исключаем по ключевым словам в названии (например, "Атлас")
        name_match = name_pattern.search(block)
        if name_match and name_keywords_lower:
            name_lower = name_match.group(1).lower()
            if any(kw in name_lower for kw in name_keywords_lower):
                stats["removed_name"] += 1
                return ""

        # 2. Исключаем по категории
        cat_match = cat_pattern.search(block)
        if cat_match and is_excluded(cat_match.group(1)):
            stats["removed_category"] += 1
            return ""

        # 3. Исключаем товары, которые поставщик пометил как недоступные
        if skip_unavailable:
            av = avail_pattern.search(block)
            if av and av.group(1).strip().lower() == "false":
                stats["removed_unavailable"] += 1
                return ""

        # 4. Исключаем товары с нулевым остатком
        qty_match = qty_pattern.search(block)
        if qty_match and int(qty_match.group(1)) == 0:
            stats["removed_no_stock"] += 1
            return ""

        # 5. Исключаем товары с некорректной ценой (0, отсутствует, и т.п.) —
        # у поставщика иногда встречаются позиции с <price>0</price>,
        # такие маркетплейс всё равно не примет.
        price_check_match = price_pattern.search(block)
        if not price_check_match or float(price_check_match.group(1)) <= 0:
            stats["removed_invalid_price"] += 1
            return ""

        # 6. Убираем скидку: заменяем price на oldprice и удаляем oldprice
        old_match = oldprice_pattern.search(block)
        if old_match:
            old_value = old_match.group(1)
            block = price_pattern.sub(f"<price>{old_value}</price>", block, count=1)
            block = oldprice_pattern.sub("", block, count=1)
            stats["discounts_removed"] += 1

        # 7. Наценка и округление до "красивого" числа.
        # Для товаров из markup_by_category — своя наценка, для остальных — markup_default.
        # Пропускается, если ENABLE_MARKUP = False — тогда остаётся оригинальная цена.
        if ENABLE_MARKUP:
            rate, special = supplier["markup_default"], False
            if cat_match:
                rate, special = get_markup(cat_match.group(1))
            if rate > 0:
                cur_price_match = price_pattern.search(block)
                if cur_price_match:
                    new_value = apply_markup(float(cur_price_match.group(1)), rate)
                    block = price_pattern.sub(f"<price>{new_value}</price>", block, count=1)
                    stats["markup_applied"] += 1
                    if special:
                        stats["markup_special"] += 1

        stats["kept"] += 1
        return block

    new_content = offer_pattern.sub(repl, content)
    return new_content, stats


def merge_supplier(base: str, supplier_content: str, supplier_name: str):
    """Добавляет в итоговый документ base товары и нужные категории другого поставщика.
    Категории переносятся только те, что реально используются оставшимися товарами
    (вместе с цепочкой родителей). Товары с ID, который уже есть в base, пропускаются
    с предупреждением. Возвращает (новый_base, добавлено_офферов, пропущено_дублей)."""
    if "</offers>" not in base or "</categories>" not in base:
        raise RuntimeError("В основном фиде нет тегов <categories>/<offers> — не могу добавить второй фид")

    existing_offer_ids = set(re.findall(r'<offer\b[^>]*\bid="([^"]+)"', base))
    existing_cat_ids = set(parse_categories(base))
    sup_parent = parse_categories(supplier_content)

    new_offers = []
    skipped = 0
    for block in re.findall(r"<offer\b.*?</offer>", supplier_content, re.DOTALL):
        oid_match = re.search(r'<offer\b[^>]*\bid="([^"]+)"', block)
        oid = oid_match.group(1) if oid_match else None
        if oid is None or oid in existing_offer_ids:
            print(f"ВНИМАНИЕ [{supplier_name}]: оффер id={oid} уже есть в итоговом фиде — пропускаю дубль.")
            skipped += 1
            continue
        existing_offer_ids.add(oid)
        new_offers.append(block)

    needed = set()
    for block in new_offers:
        cat_match = re.search(r"<categoryId>\s*([^<\s]+)\s*</categoryId>", block)
        cur = cat_match.group(1) if cat_match else None
        while cur is not None and cur not in needed:
            needed.add(cur)
            cur = sup_parent.get(cur)

    new_categories = []
    for m in re.finditer(r"<category\b([^>]*)>.*?</category>", supplier_content, re.DOTALL):
        idm = re.search(r'\bid="([^"]+)"', m.group(1))
        if not idm or idm.group(1) not in needed:
            continue
        if idm.group(1) in existing_cat_ids:
            print(f"ВНИМАНИЕ [{supplier_name}]: категория id={idm.group(1)} уже есть в итоговом фиде — "
                  f"не добавляю, проверьте, что это та же категория.")
            continue
        new_categories.append(m.group(0))

    new_base = base
    if new_categories:
        new_base = new_base.replace("</categories>", "\n".join(new_categories) + "\n</categories>", 1)
    if new_offers:
        new_base = new_base.replace("</offers>", "\n".join(new_offers) + "\n</offers>", 1)
    return new_base, len(new_offers), skipped


def merge_custom_offers(content: str, custom_path: str) -> tuple[str, int, int]:
    """Подмешивает в content собственные категории и офферы из custom_path
    (если файл существует). Цены и данные собственных офферов НЕ трогаются —
    добавляются как есть, без наценки и фильтров.
    ID офферов/категорий, которые уже встречаются в основном content,
    пропускаются (во избежание дублей), с предупреждением в лог.
    Возвращает (новый_content, добавлено_офферов, пропущено_из-за_дублей_id).
    """
    if not os.path.exists(custom_path):
        print(f"Файл со своими товарами не найден ({custom_path}) — пропускаю, это нормально, если своих товаров ещё нет.")
        return content, 0, 0

    with open(custom_path, "r", encoding="utf-8") as f:
        custom_content = f.read()

    # Убираем XML-комментарии <!-- ... -->, чтобы закомментированные примеры
    # и текст инструкций внутри них не попали в разбор как реальные данные
    custom_content = re.sub(r"<!--.*?-->", "", custom_content, flags=re.DOTALL)

    # Существующие ID категорий и офферов в основном фиде — чтобы не было дублей
    existing_category_ids = set(parse_categories(content))
    existing_offer_ids = set(re.findall(r'<offer\b[^>]*\bid="([^"]+)"', content))

    # Извлекаем свои категории (только с обязательным id)
    custom_categories = re.findall(r'<category\b[^>]*\bid="[^"]+"[^>]*>.*?</category>', custom_content, re.DOTALL)
    new_categories = []
    for cat_block in custom_categories:
        cid_match = re.search(r'\bid="([^"]+)"', cat_block)
        if cid_match and cid_match.group(1) in existing_category_ids:
            print(f"ВНИМАНИЕ: своя категория id={cid_match.group(1)} уже существует в фиде поставщика — пропускаю, используйте другой ID.")
            continue
        new_categories.append(cat_block)

    # Извлекаем свои офферы (только с обязательным id)
    custom_offers = re.findall(r'<offer\b[^>]*\bid="[^"]+"[^>]*>.*?</offer>', custom_content, re.DOTALL)
    added = 0
    skipped = 0
    new_offers = []
    for offer_block in custom_offers:
        oid_match = re.search(r'<offer\b[^>]*\bid="([^"]+)"', offer_block)
        oid = oid_match.group(1)
        if oid in existing_offer_ids:
            print(f"ВНИМАНИЕ: свой оффер id={oid} совпадает с ID из фида поставщика — пропускаю, используйте другой ID (рекомендуется диапазон 900000+).")
            skipped += 1
            continue
        new_offers.append(offer_block)
        added += 1

    new_content = content
    if new_categories:
        new_content = new_content.replace("</categories>", "\n".join(new_categories) + "\n</categories>", 1)
    if new_offers:
        new_content = new_content.replace("</offers>", "\n".join(new_offers) + "\n</offers>", 1)

    return new_content, added, skipped


def print_stats(name: str, stats: dict):
    print(f"[{name}] Оставлено офферов: {stats['kept']}")
    print(f"[{name}] Удалено по названию (ключевые слова): {stats['removed_name']}")
    print(f"[{name}] Удалено по категории: {stats['removed_category']}")
    print(f"[{name}] Удалено (available=false): {stats['removed_unavailable']}")
    print(f"[{name}] Удалено (нет в наличии, quantity=0): {stats['removed_no_stock']}")
    print(f"[{name}] Удалено (некорректная цена, 0 или отсутствует): {stats['removed_invalid_price']}")
    print(f"[{name}] Скидок убрано (price <- oldprice): {stats['discounts_removed']}")
    print(f"[{name}] Наценка применена к товарам: {stats['markup_applied']} "
          f"(из них по своим категориям: {stats['markup_special']})")


def main():
    result = None
    total_kept = 0

    for supplier in SUPPLIERS:
        name = supplier["name"]
        print(f"=== Поставщик: {name} ===")
        print(f"Скачиваю фид: {supplier['url']}")
        try:
            content = fetch_source(supplier["url"], min_size=supplier.get("min_size", 1_000_000))
            print(f"Скачано {len(content)} байт")
            if len(content) < supplier.get("min_size", 1_000_000):
                print("ВНИМАНИЕ: файл подозрительно маленький, возможно это не фид, а страница ошибки.")
                print("Первые 1000 символов ответа:")
                print(content[:1000])

            parent_of = parse_categories(content)
            print(f"Найдено категорий: {len(parent_of)}")

            filtered, stats = filter_offers(content, supplier, parent_of)
            print_stats(name, stats)
            if stats["kept"] == 0:
                raise RuntimeError("ни одного оффера не осталось — что-то не так с фидом или фильтрами")
        except Exception as e:
            if supplier.get("required", True):
                print(f"ОШИБКА [{name}]: {e}", file=sys.stderr)
                sys.exit(1)
            print(f"ВНИМАНИЕ [{name}]: поставщик пропущен из-за ошибки: {e}")
            continue

        if result is None:
            result = filtered
        else:
            result, added, skipped = merge_supplier(result, filtered, name)
            print(f"[{name}] Добавлено в итоговый фид: {added} (дублей ID пропущено: {skipped})")
        total_kept += stats["kept"]

    if result is None:
        print("ОШИБКА: ни один поставщик не обработан", file=sys.stderr)
        sys.exit(1)

    result, custom_added, custom_skipped = merge_custom_offers(result, CUSTOM_OFFERS_PATH)
    print(f"Добавлено своих товаров: {custom_added}")
    if custom_skipped:
        print(f"Пропущено своих товаров из-за конфликта ID: {custom_skipped}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"Сохранено в {OUTPUT_PATH}: всего офферов от поставщиков {total_kept} + своих {custom_added}")


if __name__ == "__main__":
    main()
