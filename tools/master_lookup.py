"""商品マスタ（knowledge/product_master.json）参照ツール。

数値の「正」となるデータへのアクセスを提供する。専門エージェントは基本的に
マニュアルの記述から回答を合成するが、検証エージェントはこのモジュール経由で
product_master.json の値と数値主張を突き合わせる。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

MASTER_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "product_master.json"


@lru_cache(maxsize=1)
def _load_master() -> dict:
    with MASTER_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def get_master_version() -> str:
    return _load_master().get("version", "unknown")


def get_product(product_id: str) -> dict | None:
    return _load_master().get("products", {}).get(product_id)


def all_products() -> dict:
    return dict(_load_master().get("products", {}))


def iter_numeric_fields():
    """(product_id, field_name, value) を全商品・全数値フィールドについて列挙する。

    検証エージェントが「マニュアルの数値主張がどの商品マスタの値と対応するか」を
    総当りで照合する際に使う。
    """
    for product_id, product in all_products().items():
        for field_name, value in product.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                yield product_id, field_name, value
