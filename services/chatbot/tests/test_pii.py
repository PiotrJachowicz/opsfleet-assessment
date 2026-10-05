from chatbot.middleware.pii import PiiStreamSanitizer, sanitize_pii, sanitize_rows
from chatbot.pii import EMAIL_TOKEN, PHONE_TOKEN


def test_sanitize_email_and_phone() -> None:
    text = "Reach jane.doe@example.com or +1 (555) 123-4567 today."
    assert sanitize_pii(text) == (
        f"Reach {EMAIL_TOKEN} or {PHONE_TOKEN} today."
    )


def test_sanitize_leaves_order_ids() -> None:
    text = "Order 1234567890 shipped; user id 42."
    assert sanitize_pii(text) == text


def test_sanitize_rows_redacts_email_column() -> None:
    payload = {
        "row_count": 1,
        "rows": [
            {
                "id": 7,
                "email": "alice@retail.test",
                "first_name": "Alice",
            }
        ],
    }
    cleaned = sanitize_rows(payload)
    assert cleaned["rows"][0]["email"] == EMAIL_TOKEN
    assert cleaned["rows"][0]["id"] == 7
    assert cleaned["rows"][0]["first_name"] == "Alice"


def test_stream_sanitizer_holds_partial_email() -> None:
    sanitizer = PiiStreamSanitizer(holdback=32)
    assert sanitizer.push("write to a@b.") == ""
    assert EMAIL_TOKEN not in sanitizer.push("co")
    final = sanitizer.finalize()
    assert EMAIL_TOKEN in final
    assert "a@b.co" not in final
