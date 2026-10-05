import uuid
from unittest.mock import patch

from chatbot.reports.store import (
    PendingDeletion,
    clear_pending_deletion,
    is_delete_confirmation,
    try_resolve_pending_deletion,
)


def test_only_exact_y_confirms_delete() -> None:
    assert is_delete_confirmation("y") is True
    assert is_delete_confirmation(" y ") is True
    assert is_delete_confirmation("Y") is False
    assert is_delete_confirmation("yes") is False
    assert is_delete_confirmation("y\nplease") is False
    assert is_delete_confirmation("delete") is False


def test_try_resolve_confirms_only_on_y() -> None:
    user_id = "user-test"
    rid = uuid.uuid4()
    clear_pending_deletion(user_id)
    from chatbot.reports import store as report_store

    report_store._pending_deletions[user_id] = PendingDeletion(
        report_id=rid,
        title="Demo",
        file_path="/tmp/demo.html",
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
        report_id=rid,
        title="Demo",
        file_path="/tmp/demo.html",
    )
    with patch("chatbot.reports.store.delete_report_for_user") as delete_mock:
        result = try_resolve_pending_deletion(user_id, "yes")
        assert result is not None
        assert result["handled"] is False
        assert result["outcome"] == "cancelled"
        delete_mock.assert_not_called()
    assert report_store.get_pending_deletion(user_id) is None
