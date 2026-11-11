import pytest

from query_reports import board_store


@pytest.fixture(autouse=True)
def store_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMBA_QUERY_BOARD_FILE", str(tmp_path / "board.json"))


def test_update_saves_and_clears_fields():
    rec = board_store.update("ABCD1234efgh", {"estado": "En curso", "nota": " revisar plan "}, "mario")
    assert rec["estado"] == "En curso" and rec["nota"] == "revisar plan" and rec["updated_by"] == "mario"
    assert "abcd1234efgh" in board_store.get_all()

    rec = board_store.update("abcd1234efgh", {"estado": ""}, "mario")
    assert "estado" not in rec and rec["nota"] == "revisar plan"

    assert board_store.update("abcd1234efgh", {"nota": ""}, "mario") is None
    assert board_store.get_all() == {}


@pytest.mark.parametrize("sql_id,changes", [
    ("../etc", {"nota": "x"}),
    ("abcd1234efgh", {"admin": "x"}),
    ("abcd1234efgh", {"nota": "x" * 5000}),
    ("abcd1234efgh", {"nota": 5}),
])
def test_update_rejects_invalid_input(sql_id, changes):
    with pytest.raises(ValueError):
        board_store.update(sql_id, changes, "mario")


def test_comentarios_firmados_y_borrado():
    c = board_store.add_comment("gr2s615xytkx7", " hola ", "ana", "dba")
    assert c["author"] == "ana" and c["role"] == "dba" and c["text"] == "hola" and c["at"]
    with pytest.raises(ValueError):
        board_store.add_comment("gr2s615xytkx7", "  ", "ana", "dba")
    with pytest.raises(PermissionError):
        board_store.delete_comment("gr2s615xytkx7", c["id"], "luis", False)
    assert board_store.delete_comment("gr2s615xytkx7", c["id"], "admin", True)
    assert board_store.get_all() == {}


def test_notifications_reach_involved_users_only_and_can_be_read():
    users = ["mario", "ana", "luis"]
    board_store.update("abcd1234efgh", {"persona": "ANA GARCIA"}, "mario")
    board_store.add_comment("abcd1234efgh", "revisa el plan", "luis", "dba")

    to = board_store.recipients("abcd1234efgh", "mario", users, "gracias @luis")
    assert to == ["ana", "luis"]
    board_store.notify("abcd1234efgh", "comentario", "mario", "gracias @luis", to)

    assert board_store.notifications_for("mario") == {"items": [], "unread": 0}
    inbox = board_store.notifications_for("ana")
    assert inbox["unread"] == 1 and inbox["items"][0]["by"] == "mario" and "to" not in inbox["items"][0]

    board_store.mark_read("ana")
    assert board_store.notifications_for("ana")["unread"] == 0
