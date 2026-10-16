from pathlib import Path

import pytest

from scripts.envelope_contract_scan import envelope_endpoints


def scan(tmp_path: Path, route: str, helper: str = "") -> dict[str, str]:
    routers = tmp_path / "server" / "routers"
    routers.mkdir(parents=True)
    (routers / "example.py").write_text(route, encoding="utf-8")
    (tmp_path / "helper.py").write_text(helper, encoding="utf-8")
    return envelope_endpoints(routers, tmp_path)


@pytest.mark.parametrize("value", ["False", "accepted", "bool(result)", "None"])
def test_direct_envelopes_ignore_format_and_nested_dictionary(tmp_path, value):
    found = scan(tmp_path, f"""
@router.post(path='/x')
def endpoint():
    return {{'details': {{'nested': True}}, 'ok': {value}}}
""")
    assert set(found) == {"/x"}


def test_imported_async_delegate_and_same_module_helper(tmp_path):
    found = scan(tmp_path, """
@router.post('/x')
async def endpoint():
    from helper import compact as run
    return await run()
""", """
raise RuntimeError('scanner must never execute application modules')

async def compact():
    return result()

def result():
    return {'ok': False, 'reason': 'too_short'}
""")
    assert set(found) == {"/x"}
    assert "(endpoint) -> helper.py:" in found["/x"]
    assert "(compact) -> helper.py:" in found["/x"]
    assert "(result)" in found["/x"]


@pytest.mark.parametrize("returned", ["{'ok': True}", "{'data': {'ok': False}}", "{'message': 'ok: False'}"])
def test_helper_without_rejection_does_not_create_an_envelope(tmp_path, returned):
    assert scan(tmp_path, """
from helper import response
@router.post('/x')
def endpoint():
    return response()
""", f"def response():\n    return {returned}\n") == {}


def test_unrelated_nested_and_adjacent_functions_do_not_belong_to_route(tmp_path):
    assert scan(tmp_path, """
@router.post('/x')
def endpoint():
    def unrelated():
        return {'ok': False}
    return {'ok': True}

def adjacent():
    return {'ok': False}
""") == {}


def test_multiple_decorators_and_delegation_cycle(tmp_path):
    found = scan(tmp_path, """
@router.get('/x')
@router.post('/y')
def endpoint():
    return helper()
def helper():
    return endpoint()
@router.get('/z')
def rejecting():
    return {'ok': False}
""")
    assert set(found) == {"/z"}


@pytest.mark.parametrize("signature,body", [
    ("response", "return response()"),
    ("", "response = factory()\n    return response()"),
    ("", "def response():\n        return {'ok': True}\n    return response()"),
])
def test_shadowed_import_is_not_followed(tmp_path, signature, body):
    assert scan(tmp_path, f"""
from helper import response
@router.post('/x')
def endpoint({signature}):
    {body}
""", "def response():\n    return {'ok': False}\n") == {}


def test_multiple_routes_share_an_imported_delegate(tmp_path):
    found = scan(tmp_path, """
from helper import response
@router.get('/x')
@router.post('/y')
def endpoint():
    return response()
""", "def response():\n    return {'ok': accepted}\n")
    assert set(found) == {"/x", "/y"}


@pytest.mark.parametrize("bindings,expected", [
    ("from helper import response\ndef response():\n    return {'ok': True}\n", set()),
    ("def response():\n    return {'ok': True}\nfrom helper import response\n", {"/x"}),
    ("from helper import response\nresponse = factory()\n", set()),
])
def test_module_binding_order_controls_the_actual_delegate(tmp_path, bindings, expected):
    found = scan(tmp_path, bindings + """
@router.post('/x')
def endpoint():
    return response()
""", "def response():\n    return {'ok': False}\n")
    assert set(found) == expected
