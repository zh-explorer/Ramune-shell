"""Tests for the protocol package."""

from ramune_shell.protocol import Request, Response, ErrorCode


def test_request_roundtrip():
    req = Request(id="test-001", method="exec", params={"command": "echo hello"})
    data = req.to_bytes()
    req2, consumed = Request.from_buffer(bytearray(data))
    assert consumed == len(data)
    assert req2 == req


def test_response_ok_roundtrip():
    resp = Response.ok("test-001", {"stdout": "hello", "exit_code": 0})
    data = resp.to_bytes()
    resp2, _ = Response.from_buffer(bytearray(data))
    assert resp2.id == "test-001"
    assert resp2.result == {"stdout": "hello", "exit_code": 0}
    assert resp2.error is None


def test_response_fail_roundtrip():
    err = Response.fail("test-002", ErrorCode.METHOD_NOT_FOUND, "no such method")
    data = err.to_bytes()
    err2, _ = Response.from_buffer(bytearray(data))
    assert err2.id == "test-002"
    assert err2.result is None
    assert err2.error.code == ErrorCode.METHOD_NOT_FOUND
    assert err2.error.message == "no such method"


def test_request_default_params():
    req = Request(id="test-003", method="ping")
    assert req.params == {}
    data = req.to_bytes()
    req2, _ = Request.from_buffer(bytearray(data))
    assert req2 == req


def test_decode_incomplete_buffer():
    req = Request(id="test-004", method="ping")
    data = req.to_bytes()
    # partial header
    msg, consumed = Request.from_buffer(bytearray(data[:2]))
    assert msg is None
    assert consumed == 0
    # partial payload
    msg, consumed = Request.from_buffer(bytearray(data[: len(data) - 1]))
    assert msg is None
    assert consumed == 0


def test_decode_multiple_messages():
    r1 = Request(id="a", method="ping")
    r2 = Request(id="b", method="exec", params={"command": "ls"})
    buf = bytearray(r1.to_bytes() + r2.to_bytes())

    msg1, consumed1 = Request.from_buffer(buf)
    assert msg1 == r1
    buf = buf[consumed1:]

    msg2, consumed2 = Request.from_buffer(buf)
    assert msg2 == r2


def test_binary_data_in_result():
    """Ensure msgpack handles bytes natively."""
    image_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    resp = Response.ok("test-005", {"image": image_data})
    data = resp.to_bytes()
    resp2, _ = Response.from_buffer(bytearray(data))
    assert resp2.result["image"] == image_data
