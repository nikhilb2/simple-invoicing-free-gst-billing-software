"""Unit tests for the NUL-character guard (#775); no database needed."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.core.request_text_safety import _contains_nul, _is_json_body, reject_nul_characters

NUL = "\x00"


def test_contains_nul_plain_and_scalars():
    assert _contains_nul(f"a{NUL}b")
    assert not _contains_nul("clean")
    for scalar in (None, 0, 1.5, True, False):
        assert not _contains_nul(scalar)


def test_contains_nul_nested_lists_and_dicts():
    assert _contains_nul([1, ["ok", [{"a": [f"x{NUL}"]}]]])
    assert not _contains_nul([1, ["ok", [{"a": ["x"]}]], None])


def test_contains_nul_dict_keys():
    assert _contains_nul({f"k{NUL}": "v"})
    assert not _contains_nul({"k": "v"})


def test_contains_nul_empty_values():
    assert not _contains_nul("")
    assert not _contains_nul([])
    assert not _contains_nul({})


def test_is_json_body_matches_fastapi_rule():
    assert _is_json_body(None)
    assert _is_json_body("")
    assert _is_json_body("application/json")
    assert _is_json_body("Application/JSON; charset=utf-8")
    assert _is_json_body("application/vnd.api+json")
    assert not _is_json_body("text/plain")
    assert not _is_json_body("multipart/form-data; boundary=x")
    assert not _is_json_body("application/x-www-form-urlencoded")


def _client() -> TestClient:
    app = FastAPI(dependencies=[Depends(reject_nul_characters)])

    @app.post("/echo")
    async def echo(payload: dict):
        return payload

    @app.get("/item/{name}")
    async def item(name: str):
        return {"name": name}

    @app.post("/form")
    async def form():
        return {"ok": True}

    return TestClient(app)


BODY = '{"a": "x\\u0000y"}'


def test_json_content_types_are_scanned():
    client = _client()
    for content_type in ("application/json", "application/vnd.api+json"):
        r = client.post("/echo", content=BODY, headers={"content-type": content_type})
        assert r.status_code == 422, content_type


def test_missing_content_type_is_scanned():
    client = _client()
    r = client.post("/echo", content=BODY, headers={"content-type": ""})
    assert r.status_code == 422


def test_clean_json_passes_and_empty_body_is_left_to_fastapi():
    client = _client()
    assert client.post("/echo", json={"a": "ok"}).status_code == 200
    r = client.post("/echo", content=b"", headers={"content-type": "application/json"})
    assert "NUL" not in r.text


def test_deeply_nested_json_is_not_raised_by_the_guard():
    import asyncio

    from starlette.requests import Request

    depth = 100000
    body = ("[" * depth + "]" * depth).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/echo",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "path_params": {},
        },
        receive,
    )
    # RecursionError is swallowed: FastAPI answers as it would without the guard.
    assert asyncio.run(reject_nul_characters(request)) is None


def _nested(depth: int, leaf: object) -> str:
    import json

    return "[" * depth + json.dumps(leaf) + "]" * depth


def test_contains_nul_deep_nesting_does_not_recurse():
    import json

    for depth in (600, 900):
        assert _contains_nul(json.loads(_nested(depth, "a\x00b"))) is True
        assert _contains_nul(json.loads(_nested(depth, "ok"))) is False
    # Dict nesting too.
    deep: object = {"k": "\x00"}
    for _ in range(600):
        deep = {"k": deep}
    assert _contains_nul(deep) is True


def test_deep_nesting_over_http_is_a_handled_response_not_a_500():
    client = _client()
    headers = {"content-type": "application/json"}
    for depth in (600, 2000, 100000):
        r = client.post("/echo", content=_nested(depth, "ok").encode(), headers=headers)
        assert r.status_code < 500, (depth, r.status_code)
    r = client.post("/echo", content=_nested(600, "a\x00b").encode(), headers=headers)
    assert r.status_code == 422
    assert "NUL" in r.text


def test_form_encoded_and_path_params_are_scanned():
    client = _client()
    r = client.post("/form", content="a=x%00y", headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 422
    r = client.post("/form", content="a=xy", headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200
    assert client.get("/item/a%00b").status_code == 422
    assert client.get("/item/ab").status_code == 200


def test_multipart_is_not_scanned():
    client = _client()
    r = client.post("/form", files={"f": ("f.bin", b"abc\x00def")})
    assert r.status_code == 200
