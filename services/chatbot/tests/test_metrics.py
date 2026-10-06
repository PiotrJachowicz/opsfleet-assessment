from chatbot.middleware import metrics as metrics_mod
from chatbot.middleware.metrics import (
    ChatTurnTimer,
    record_auth_failure,
    record_bq_outcome,
    record_model_retry,
    record_report_delete,
    record_tool_result,
)


def _counter_value(counter, **labels) -> float:
    if labels:
        return counter.labels(**labels)._value.get()
    return counter._value.get()


def test_record_helpers_increment_counters() -> None:
    before_auth = _counter_value(metrics_mod.AUTH_FAILURES)
    record_auth_failure()
    assert _counter_value(metrics_mod.AUTH_FAILURES) == before_auth + 1

    before_bq = _counter_value(metrics_mod.BQ_QUERIES, outcome="empty")
    record_bq_outcome("empty")
    assert _counter_value(metrics_mod.BQ_QUERIES, outcome="empty") == before_bq + 1

    before_retry = _counter_value(metrics_mod.MODEL_RETRIES, result="retry")
    record_model_retry("retry")
    assert (
        _counter_value(metrics_mod.MODEL_RETRIES, result="retry") == before_retry + 1
    )

    before_del = _counter_value(metrics_mod.REPORT_DELETES, outcome="confirmed")
    record_report_delete("confirmed")
    assert (
        _counter_value(metrics_mod.REPORT_DELETES, outcome="confirmed")
        == before_del + 1
    )


def test_record_tool_result_classifies_errors() -> None:
    before_ok = _counter_value(metrics_mod.TOOL_CALLS, tool="run_sql", status="ok")
    before_err = _counter_value(
        metrics_mod.TOOL_CALLS, tool="run_sql", status="error"
    )
    record_tool_result("run_sql", '{"row_count": 1}')
    record_tool_result("run_sql", "status: sql_rejected\nrepair_required: true")
    assert (
        _counter_value(metrics_mod.TOOL_CALLS, tool="run_sql", status="ok")
        == before_ok + 1
    )
    assert (
        _counter_value(metrics_mod.TOOL_CALLS, tool="run_sql", status="error")
        == before_err + 1
    )


def test_chat_turn_timer_records_status_and_latency() -> None:
    before = _counter_value(metrics_mod.CHAT_TURNS, status="error")
    timer = ChatTurnTimer()
    timer.mark("error")
    timer.finish()
    timer.finish()  # idempotent
    assert _counter_value(metrics_mod.CHAT_TURNS, status="error") == before + 1
