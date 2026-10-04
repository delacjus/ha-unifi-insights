import pytest
from custom_components.unifi_insights.api.base import _redact

def test_redact():
    assert _redact('{"password": "my:secret:password"}') == '{"password": "**REDACTED**"}'
    assert _redact('{"token":"abc:def"}') == '{"token":"**REDACTED**"}'
    assert _redact('{"apiKey": "my_api_key"}') == '{"apiKey": "**REDACTED**"}'

if __name__ == "__main__":
    test_redact()
    print("All tests pass!")
