from __future__ import annotations

import enum
import json
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel

from cogos.db.repository import RdsBackend


class TestJsonSafe:
    def test_none_passthrough(self):
        assert RdsBackend.json_safe(None) is None

    def test_dict_passthrough(self):
        d = {"key": "value"}
        assert RdsBackend.json_safe(d) is d

    def test_list_passthrough(self):
        lst = [1, 2, 3]
        assert RdsBackend.json_safe(lst) is lst

    def test_empty_dict(self):
        assert RdsBackend.json_safe({}) == {}

    def test_empty_list(self):
        assert RdsBackend.json_safe([]) == []

    def test_string_roundtrips(self):
        result = RdsBackend.json_safe("hello")
        assert result == "hello"

    def test_int_roundtrips(self):
        result = RdsBackend.json_safe(42)
        assert result == 42

    def test_enum_converted(self):
        class Color(enum.Enum):
            RED = "red"

        result = RdsBackend.json_safe(Color.RED)
        assert isinstance(result, str)
        assert "RED" in result or "red" in result

    def test_pydantic_model_converted(self):
        class MyModel(BaseModel):
            name: str
            value: int

        result = RdsBackend.json_safe(MyModel(name="test", value=42))
        assert result is not None
        assert isinstance(result, (dict, str))

    def test_dict_with_uuid_values(self):
        d = {"id": uuid4(), "ts": datetime.now()}
        result = RdsBackend.json_safe(d)
        assert result is d

    def test_nested_non_serializable(self):
        d = {"ids": [uuid4(), uuid4()]}
        result = RdsBackend.json_safe(d)
        assert result is d


class TestToParam:
    def _make_backend(self):
        return RdsBackend.__new__(RdsBackend)

    def test_dict_serialized_with_default_str(self):
        b = self._make_backend()
        uid = UUID("12345678-1234-5678-1234-567812345678")
        param = b._to_param("meta", {"id": uid})
        assert param["value"]["stringValue"] == '{"id": "12345678-1234-5678-1234-567812345678"}'

    def test_list_serialized(self):
        b = self._make_backend()
        param = b._to_param("items", [1, "two", 3])
        assert param["value"]["stringValue"] == '[1, "two", 3]'

    def test_none_is_null(self):
        b = self._make_backend()
        param = b._to_param("x", None)
        assert param["value"]["isNull"] is True

    def test_string_passthrough(self):
        b = self._make_backend()
        param = b._to_param("name", "hello")
        assert param["value"]["stringValue"] == "hello"
