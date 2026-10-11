from types import SimpleNamespace
from core.desktop_accessibility import WindowsAccessibility


def element(name="editor", kind="Document", text="اختبار عربي", password=False, children=()):
    return SimpleNamespace(element_info=SimpleNamespace(name=name, control_type=kind, automation_id="test",
        element=SimpleNamespace(CurrentIsPassword=password, CurrentIsOffscreen=False)),
        iface_text=SimpleNamespace(DocumentRange=SimpleNamespace(GetText=lambda limit: text[:limit])),
        children=lambda: list(children))


def reader(root):
    return WindowsAccessibility(desktop=SimpleNamespace(window=lambda **kwargs:
        SimpleNamespace(wrapper_object=lambda: root)))


def test_verification_checks_editor_content_not_button_label():
    obj = reader(element(kind="Window", text="", children=[element(kind="Button", name="secret", text="secret")]))
    assert obj.verify_text(1, "secret")["verified"] is False
    assert reader(element()).verify_text(1, "اختبار عربي")["verified"] is True


def test_password_field_and_descendants_are_excluded():
    obj = reader(element(kind="Window", text="", children=[element(password=True, children=[element(text="secret")])]))
    result = obj.read(1)
    assert len(result["elements"]) == 1
    assert "secret" not in str(result)


def test_unknown_password_status_is_not_read():
    root = element(text="private")
    root.element_info.element = None
    assert reader(root).read(1)["elements"] == []


def test_hidden_editor_cannot_verify_text_from_an_old_tab():
    hidden = element(text="old tab")
    hidden.element_info.element.CurrentIsOffscreen = True
    assert reader(element(kind="Window", children=[hidden])).verify_text(1, "old tab")["verified"] is False


def test_tree_and_editor_text_are_bounded():
    root = element(children=[element(text="x" * 5000) for _ in range(50)])
    result = reader(root).read(1)
    assert len(result["elements"]) == 31
    assert all(len(row["text"]) <= 2000 for row in result["elements"])
