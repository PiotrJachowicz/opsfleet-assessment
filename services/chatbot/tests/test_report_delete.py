import uuid
from unittest.mock import patch

from chatbot.reports.store import (
    PendingDeletion,
    PendingReportRef,
    clear_pending_deletion,
    is_delete_confirmation,
    normalize_mentioned_clients,
    try_resolve_pending_deletion,
)


def test_only_exact_y_confirms_delete() -> None:
    assert is_delete_confirmation("y") is True
    assert is_delete_confirmation(" y ") is True
    assert is_delete_confirmation("Y") is False
    assert is_delete_confirmation("yes") is False
    assert is_delete_confirmation("y\nplease") is False
    assert is_delete_confirmation("delete") is False


def test_normalize_mentioned_clients_lowercases_and_dedupes() -> None:
    assert normalize_mentioned_clients(["Client X", " client x ", "Acme"]) == [
        "client x",
        "acme",
    ]
    assert normalize_mentioned_clients(None) == []
    assert normalize_mentioned_clients(["", "  "]) == []


def test_try_resolve_confirms_only_on_y() -> None:
    user_id = "user-test"
    rid = uuid.uuid4()
    clear_pending_deletion(user_id)
    from chatbot.reports import store as report_store

    report_store._pending_deletions[user_id] = PendingDeletion(
        reports=(
            PendingReportRef(
                report_id=rid,
                title="Demo",
                file_path="/tmp/demo.html",
            ),
        )
    )
    with patch(
        "chatbot.reports.store.delete_report_for_user",
        return_value={"report_id": str(rid), "title": "Demo", "deleted": True},
    ) as delete_mock:
        result = try_resolve_pending_deletion(user_id, "y")
        assert result is not None
        assert result["handled"] is True
        assert result["outcome"] == "deleted"
        delete_mock.assert_called_once_with(rid, user_id)

    report_store._pending_deletions[user_id] = PendingDeletion(
        reports=(
            PendingReportRef(
                report_id=rid,
                title="Demo",
                file_path="/tmp/demo.html",
            ),
        )
    )
    with patch("chatbot.reports.store.delete_report_for_user") as delete_mock:
        result = try_resolve_pending_deletion(user_id, "yes")
        assert result is not None
        assert result["handled"] is False
        assert result["outcome"] == "cancelled"
        delete_mock.assert_not_called()
    assert report_store.get_pending_deletion(user_id) is None


def test_try_resolve_confirms_bulk_batch() -> None:
    user_id = "user-bulk"
    rid1, rid2 = uuid.uuid4(), uuid.uuid4()
    clear_pending_deletion(user_id)
    from chatbot.reports import store as report_store

    report_store._pending_deletions[user_id] = PendingDeletion(
        reports=(
            PendingReportRef(rid1, "A", "/tmp/a.html"),
            PendingReportRef(rid2, "B", "/tmp/b.html"),
        )
    )
    with patch(
        "chatbot.reports.store.delete_report_for_user",
        side_effect=[
            {"report_id": str(rid1), "title": "A", "deleted": True},
            {"report_id": str(rid2), "title": "B", "deleted": True},
        ],
    ) as delete_mock:
        result = try_resolve_pending_deletion(user_id, "y")
        assert result is not None
        assert result["outcome"] == "deleted"
        assert "A" in result["message"] and "B" in result["message"]
        assert delete_mock.call_count == 2
