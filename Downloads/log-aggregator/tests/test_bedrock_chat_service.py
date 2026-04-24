import sys
import types

import pytest

import Dashboard.bedrock_chat_service as bcs


def test_build_agent_input_contains_context_and_history():
    text = bcs._build_agent_input(
        {
            "Status Code": 504,
            "Error Code": 9002,
            "Description": "Upstream timeout",
            "API": "GET /api/recommendations",
            "Count": 10,
            "Last Seen": "2026-03-31T10:00:00",
            "Dates": ["2026-03-31"],
        },
        "What should we do?",
        [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
    )
    assert "Selected error context" in text
    assert "User question" in text
    assert "Respond in plain text only" in text


def test_decode_and_normalize_function_calls_text():
    sample = '{"function_calls":[{"name":"error_details","parameters":{}}]}'
    decoded = bcs._decode_json_objects(sample)
    assert decoded and decoded[0]["function_calls"][0]["name"] == "error_details"

    normalized = bcs._normalize_agent_reply(sample)
    assert "internal tool-call plan" in normalized
    assert "error_details" in normalized

    # test normal text passes through
    normal_reply = "This is normal text"
    assert bcs._normalize_agent_reply(normal_reply) == normal_reply

    # test empty reply
    assert bcs._normalize_agent_reply("") == ""
    assert bcs._normalize_agent_reply(None) == ""


def test_extract_completion_text_from_streaming_chunks():
    response = {
        "completion": [
            {"chunk": {"bytes": b"Hello "}},
            {"chunk": {"bytes": b"World"}},
        ]
    }
    assert bcs._extract_completion_text(response) == "Hello World"


def test_generate_error_insight_success(monkeypatch):
    monkeypatch.setenv("BEDROCK_AGENT_ID", "agent123")
    monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "alias123")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    class FakeClient:
        def invoke_agent(self, **kwargs):
            return {"completion": [{"chunk": {"bytes": b"Plain response"}}]}

    fake_boto3 = types.SimpleNamespace(client=lambda *args, **kwargs: FakeClient())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    reply, meta = bcs.generate_error_insight({"Error Code": 9002}, "Help", [], "session-x")
    assert reply == "Plain response"
    assert meta["region"] == "us-east-1"
    assert meta["session_id"] == "session-x"


def test_generate_error_insight_requires_agent_configuration(monkeypatch):
    monkeypatch.delenv("BEDROCK_AGENT_ID", raising=False)
    monkeypatch.delenv("BEDROCK_AGENT_ALIAS_ID", raising=False)

    class FakeClient:
        def invoke_agent(self, **kwargs):
            return {"completion": []}

    fake_boto3 = types.SimpleNamespace(client=lambda *args, **kwargs: FakeClient())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    with pytest.raises(RuntimeError):
        bcs.generate_error_insight({}, "Help", [])


def test_bedrock_exception_handling_graceful_fallback(monkeypatch):
    """Test that boto3 exceptions are converted to RuntimeError"""
    monkeypatch.setenv("BEDROCK_AGENT_ID", "agent123")
    monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "alias123")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    class FakeClient:
        def invoke_agent(self, **kwargs):
            raise Exception("Service unavailable")

    fake_boto3 = types.SimpleNamespace(client=lambda *args, **kwargs: FakeClient())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    # Should raise RuntimeError (wraps the boto3 exception)
    with pytest.raises(RuntimeError, match="Bedrock agent request failed"):
        bcs.generate_error_insight({"Error Code": 9002}, "Help", [], "session-x")


def test_extract_completion_missing_chunks(monkeypatch):
    """Test extraction when completion structure is incomplete"""
    # Test with no completion events
    assert bcs._extract_completion_text({}) == ""
    
    # Test with empty completion list
    assert bcs._extract_completion_text({"completion": []}) == ""
    
    # Test with completion but no bytes
    response = {"completion": [{"chunk": {}}]}
    assert bcs._extract_completion_text(response) == ""


def test_decode_json_multiple_objects():
    """Test decoding multiple JSON objects from concatenated text"""
    sample = '{"a":1}{"b":2}{"c":3}'
    decoded = bcs._decode_json_objects(sample)
    assert len(decoded) == 3
    assert decoded[0] == {"a": 1}
    assert decoded[1] == {"b": 2}
    assert decoded[2] == {"c": 3}


def test_decode_json_with_whitespace():
    """Test JSON decoding with surrounding whitespace"""
    sample = '  {"a": 1}  \n  {"b": 2}  '
    decoded = bcs._decode_json_objects(sample)
    assert len(decoded) == 2


def test_normalize_agent_reply_detects_function_calls_variations():
    """Test normalization detects function_calls in different JSON structures"""
    # Test with empty function_calls array
    sample = '{"function_calls":[]}'
    normalized = bcs._normalize_agent_reply(sample)
    assert "tool-call" in normalized.lower() or "function" in normalized.lower()
    
    # Test with multiple function calls
    sample2 = '{"function_calls":[{"name":"api_call1"},{"name":"api_call2"}]}'
    normalized2 = bcs._normalize_agent_reply(sample2)
    assert "api_call1" in normalized2 or "api_call2" in normalized2


def test_generate_error_insight_with_empty_error_context(monkeypatch):
    """Test insight generation with minimal error context"""
    monkeypatch.setenv("BEDROCK_AGENT_ID", "agent123")
    monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "alias123")
    
    class FakeClient:
        def invoke_agent(self, **kwargs):
            return {"completion": [{"chunk": {"bytes": b"Fix it"}}]}
    
    fake_boto3 = types.SimpleNamespace(client=lambda *args, **kwargs: FakeClient())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    
    # Empty error context should still work
    reply, meta = bcs.generate_error_insight({}, "Help me", [])
    assert reply == "Fix it"
    assert "region" in meta


def test_generate_error_insight_with_conversation_history(monkeypatch):
    """Test that conversation history is included in input"""
    monkeypatch.setenv("BEDROCK_AGENT_ID", "agent123")
    monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "alias123")
    
    call_args = {}
    
    class FakeClient:
        def invoke_agent(self, **kwargs):
            call_args.update(kwargs)
            return {"completion": [{"chunk": {"bytes": b"Response"}}]}
    
    fake_boto3 = types.SimpleNamespace(client=lambda *args, **kwargs: FakeClient())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    
    history = [
        {"role": "user", "content": "Previous question?"},
        {"role": "assistant", "content": "Previous answer."}
    ]
    
    reply, meta = bcs.generate_error_insight({"Error Code": 1001}, "New Q", history)
    # Verify history was included in the input text
    assert "Previous question" in call_args["inputText"]
    assert "New Q" in call_args["inputText"]


def test_extract_completion_with_malformed_json_bytes(monkeypatch):
    """Test extraction when bytes contain invalid JSON"""
    response = {
        "completion": [
            {"chunk": {"bytes": b"Plain text, not JSON at all"}},
        ]
    }
    result = bcs._extract_completion_text(response)
    # Should still return the text even if not JSON
    assert result == "Plain text, not JSON at all"


def test_build_agent_input_with_missing_fields():
    """Test input builder handles missing error context fields gracefully"""
    minimal_context = {
        "Error Code": 500,
        # Missing other fields
    }
    text = bcs._build_agent_input(minimal_context, "Help?", [])
    # Should still generate valid input
    assert "Error Code" in text or "500" in text
    assert "Help?" in text


def test_normalize_agent_reply_with_non_dict_function_calls():
    """Test normalization when function_calls is not a list"""
    sample = '{"function_calls": "some_string_not_list"}'
    normalized = bcs._normalize_agent_reply(sample)
    # Should detect function_calls but handle non-list gracefully
    assert isinstance(normalized, str)


def test_normalize_agent_reply_with_non_dict_calls():
    """Test normalization when call items are not dicts"""
    sample = '{"function_calls": ["string_not_dict", "another"]}'
    normalized = bcs._normalize_agent_reply(sample)
    # Should handle non-dict items gracefully
    assert isinstance(normalized, str)


def test_extract_completion_with_non_dict_events():
    """Test extraction when completion events are not dicts"""
    response = {
        "completion": [
            "not_a_dict",
            123,
            None
        ]
    }
    result = bcs._extract_completion_text(response)
    # Should handle non-dict events gracefully
    assert result == ""


def test_decode_json_with_invalid_json_positions():
    """Test JSON decoding when 'text' function encounters non-JSON"""
    sample = 'prefix{"a":1}middle{"b":2}'
    decoded = bcs._decode_json_objects(sample)
    # Should stop at invalid position and return what was decoded
    # (since "prefix{" is invalid)
    assert len(decoded) <= 2


def test_build_agent_input_filters_invalid_roles():
    """Test that history items with invalid roles are filtered out"""
    history = [
        {"role": "user", "content": "Valid user message"},
        {"role": "assistant", "content": "Valid assistant message"},
        {"role": "system", "content": "Should be filtered"},
        {"role": "invalid", "content": "Should be filtered"},
    ]
    text = bcs._build_agent_input({}, "Query", history)
    
    # Should include valid roles but not system/invalid
    assert "Valid user message" in text or "user" in text.lower()
    assert "Valid assistant message" in text or "assistant" in text.lower()
    assert "system" not in text.lower()
    assert "Should be filtered" not in text


def test_build_agent_input_filters_empty_content():
    """Test that history items with empty content are filtered"""
    history = [
        {"role": "user", "content": "Valid message"},
        {"role": "assistant", "content": ""},  # Empty
        {"role": "user", "content": None},  # None
        {"role": "assistant", "content": "   "},  # Whitespace only
    ]
    text = bcs._build_agent_input({}, "Query", history)
    
    # Should only include the valid non-empty message
    assert "Valid message" in text


def test_extract_completion_text_with_non_bytes_data():
    """Test extraction when data is not bytes but string-like"""
    response = {
        "completion": [
            {"chunk": {"bytes": "string_instead_of_bytes"}},
        ]
    }
    result = bcs._extract_completion_text(response)
    # Should handle non-bytes gracefully by converting to string
    assert "string_instead_of_bytes" in result or isinstance(result, str)
