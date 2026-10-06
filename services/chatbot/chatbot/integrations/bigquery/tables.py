"""Fully-qualified thelook_ecommerce table names (single source of truth)."""

from __future__ import annotations

BQ_PROJECT = "bigquery-public-data"
BQ_DATASET = "thelook_ecommerce"
BQ_DATASET_FQN = f"{BQ_PROJECT}.{BQ_DATASET}"

ORDERS = f"{BQ_DATASET_FQN}.orders"
ORDER_ITEMS = f"{BQ_DATASET_FQN}.order_items"
PRODUCTS = f"{BQ_DATASET_FQN}.products"
USERS = f"{BQ_DATASET_FQN}.users"

ALLOWED_TABLES = frozenset({ORDERS, ORDER_ITEMS, PRODUCTS, USERS})
