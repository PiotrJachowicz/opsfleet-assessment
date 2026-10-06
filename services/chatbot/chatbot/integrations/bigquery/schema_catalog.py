"""Static schema notes for thelook_ecommerce (assignment tables only)."""

from chatbot.integrations.bigquery.tables import (
    BQ_DATASET_FQN,
    ORDER_ITEMS,
    ORDERS,
    PRODUCTS,
    USERS,
)

SCHEMA_TEXT = f"""
Dataset: {BQ_DATASET_FQN}
Always use fully-qualified table names.

tables:
  {ORDERS}
    - order_id INT64
    - user_id INT64
    - status STRING
    - gender STRING
    - created_at TIMESTAMP
    - returned_at TIMESTAMP
    - shipped_at TIMESTAMP
    - delivered_at TIMESTAMP
    - num_of_item INT64

  {ORDER_ITEMS}
    - id INT64
    - order_id INT64
    - user_id INT64
    - product_id INT64
    - inventory_item_id INT64
    - status STRING
    - created_at TIMESTAMP
    - shipped_at TIMESTAMP
    - delivered_at TIMESTAMP
    - returned_at TIMESTAMP
    - sale_price FLOAT64

  {PRODUCTS}
    - id INT64
    - cost FLOAT64
    - category STRING
    - name STRING
    - brand STRING
    - retail_price FLOAT64
    - department STRING
    - sku STRING
    - distribution_center_id INT64

  {USERS}
    - id INT64
    - first_name STRING
    - last_name STRING
    - email STRING
    - age INT64
    - gender STRING
    - state STRING
    - street_address STRING
    - postal_code STRING
    - city STRING
    - country STRING
    - latitude FLOAT64
    - longitude FLOAT64
    - traffic_source STRING
    - created_at TIMESTAMP
""".strip()
