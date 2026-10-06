from chatbot.auth import (
    AuthContext,
    AuthError,
    mint_access_token,
    verify_access_token,
)
from chatbot.integrations.bigquery.brand_scope import apply_brand_scope
from chatbot.integrations.bigquery.sql_guard import validate_readonly_sql
from chatbot.integrations.bigquery.tables import ORDER_ITEMS, PRODUCTS

SECRET = "test-jwt-secret-at-least-32-bytes!!"


def test_mint_and_verify_preset_token() -> None:
    token = mint_access_token(preset_key="calvin", secret=SECRET)
    ctx = verify_access_token(token, SECRET)
    assert ctx.user_id == "brand-calvin"
    assert ctx.allowed_brands == ("Calvin Klein",)
    assert not ctx.is_admin


def test_admin_token_is_unscoped() -> None:
    token = mint_access_token(preset_key="admin", secret=SECRET)
    ctx = verify_access_token(token, SECRET)
    assert ctx.is_admin
    assert ctx.allowed_brands == ()


def test_bad_secret_rejected() -> None:
    token = mint_access_token(preset_key="admin", secret=SECRET)
    try:
        verify_access_token(token, "other-secret-also-long-enough!!")
        assert False, "expected AuthError"
    except AuthError:
        pass


def test_products_and_order_items_are_rewritten() -> None:
    auth = AuthContext(user_id="brand-levis", brands=("Levi's",))
    sql = validate_readonly_sql(f"SELECT SUM(sale_price) FROM `{ORDER_ITEMS}`")
    scoped = apply_brand_scope(sql, auth)
    assert "Levi" in scoped
    assert "product_id IN" in scoped.replace("\n", " ")
    assert "brand IN" in scoped.replace("\n", " ")


def test_admin_sql_unchanged() -> None:
    auth = AuthContext(user_id="admin", brands=("*",))
    sql = validate_readonly_sql(f"SELECT brand FROM `{PRODUCTS}`")
    assert apply_brand_scope(sql, auth) == sql
