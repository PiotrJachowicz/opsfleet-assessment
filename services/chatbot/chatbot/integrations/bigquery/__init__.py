"""BigQuery integration package.

Keep this module free of tool/config imports so ``tables`` can be imported from
``chatbot.config`` without a circular dependency.
"""

from chatbot.integrations.bigquery.tables import (
    ALLOWED_TABLES,
    BQ_DATASET_FQN,
    ORDER_ITEMS,
    ORDERS,
    PRODUCTS,
    USERS,
)

__all__ = [
    "ALLOWED_TABLES",
    "BQ_DATASET_FQN",
    "ORDER_ITEMS",
    "ORDERS",
    "PRODUCTS",
    "USERS",
]
