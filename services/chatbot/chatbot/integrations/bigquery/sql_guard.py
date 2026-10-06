from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from chatbot.integrations.bigquery.tables import (
    ALLOWED_TABLES,
    BQ_DATASET,
    BQ_PROJECT,
)

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|"
    r"call|execute|export|load|assert)\b",
    re.IGNORECASE,
)


class SqlGuardError(ValueError):
    pass


def _part_name(part: object | None) -> str | None:
    if part is None:
        return None
    if isinstance(part, str):
        return part
    name = getattr(part, "name", None)
    return str(name) if name else None


def _normalize_table_name(table: exp.Table) -> str | None:
    parts = [
        name
        for name in (
            _part_name(table.catalog),
            _part_name(table.db),
            _part_name(table.this),
        )
        if name
    ]
    if len(parts) == 3:
        return ".".join(parts)
    if len(parts) == 2 and parts[0] == BQ_DATASET:
        return f"{BQ_PROJECT}.{parts[0]}.{parts[1]}"
    return ".".join(parts) if parts else None


def validate_readonly_sql(sql: str) -> str:
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise SqlGuardError("SQL is empty")
    if ";" in cleaned:
        raise SqlGuardError("Multiple statements are not allowed")
    if _FORBIDDEN.search(cleaned):
        raise SqlGuardError("Only read-only SELECT/WITH queries are allowed")

    try:
        statements = sqlglot.parse(cleaned, read="bigquery")
    except sqlglot.errors.ParseError as exc:
        raise SqlGuardError(f"SQL parse error: {exc}") from exc

    if len(statements) != 1 or statements[0] is None:
        raise SqlGuardError("Exactly one SQL statement is required")

    tree = statements[0]
    root = tree.this if isinstance(tree, exp.With) else tree
    if not isinstance(root, (exp.Select, exp.Union)):
        raise SqlGuardError("Only SELECT/WITH queries are allowed")

    referenced: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = _normalize_table_name(table)
        if name is None or name.count(".") == 0:
            continue
        referenced.add(name)

    if not referenced:
        raise SqlGuardError(
            f"Query must reference at least one allowed {BQ_DATASET} table "
            "using a fully-qualified name"
        )

    unknown = sorted(referenced - ALLOWED_TABLES)
    if unknown:
        raise SqlGuardError(
            "Disallowed tables: "
            + ", ".join(unknown)
            + ". Allowed: "
            + ", ".join(sorted(ALLOWED_TABLES))
        )

    return cleaned
