"""Deterministic brand-scope injection into read-only BigQuery SQL."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from chatbot.auth import AuthContext
from chatbot.integrations.bigquery.sql_guard import SqlGuardError, _normalize_table_name
from chatbot.integrations.bigquery.tables import ORDER_ITEMS, PRODUCTS


def _brand_in_predicate(brands: tuple[str, ...]) -> exp.Expression:
    return exp.In(
        this=exp.column("brand"),
        expressions=[exp.Literal.string(b) for b in brands],
    )


def _scoped_products_subquery(brands: tuple[str, ...]) -> exp.Subquery:
    """(SELECT * FROM products WHERE brand IN (...))"""
    select = (
        exp.select(exp.Star())
        .from_(exp.table_(PRODUCTS, quoted=True))
        .where(_brand_in_predicate(brands))
    )
    return exp.Subquery(this=select)


def _scoped_order_items_subquery(brands: tuple[str, ...]) -> exp.Subquery:
    """order_items rows whose product_id is in brand-scoped products."""
    products_ids = (
        exp.select(exp.column("id"))
        .from_(exp.table_(PRODUCTS, quoted=True))
        .where(_brand_in_predicate(brands))
    )
    select = (
        exp.select(exp.Star())
        .from_(exp.table_(ORDER_ITEMS, quoted=True))
        .where(
            exp.In(
                this=exp.column("product_id"),
                expressions=[products_ids],
            )
        )
    )
    return exp.Subquery(this=select)


def apply_brand_scope(sql: str, auth: AuthContext | None) -> str:
    """Rewrite products / order_items references for non-admin brand scopes.

    Admin (brands contains ``*``) or missing auth leaves SQL unchanged.
    """
    if auth is None or auth.is_admin:
        return sql

    brands = auth.allowed_brands
    if not brands:
        raise SqlGuardError("authenticated user has no brand scopes")

    try:
        statements = sqlglot.parse(sql, read="bigquery")
    except sqlglot.errors.ParseError as exc:
        raise SqlGuardError(f"SQL parse error: {exc}") from exc

    if len(statements) != 1 or statements[0] is None:
        raise SqlGuardError("Exactly one SQL statement is required")

    tree = statements[0]
    for table in list(tree.find_all(exp.Table)):
        name = _normalize_table_name(table)
        if name == PRODUCTS:
            replacement = _scoped_products_subquery(brands)
        elif name == ORDER_ITEMS:
            replacement = _scoped_order_items_subquery(brands)
        else:
            continue

        alias = table.alias_or_name
        if alias:
            replacement = replacement.as_(alias)
        table.replace(replacement)

    return tree.sql(dialect="bigquery")
