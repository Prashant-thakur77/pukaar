from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from Pukaar.core import settings as settings_module


@pytest.fixture(autouse=True)
def clear_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


def test_litert_runtime_health_reports_missing_dependency(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(tmp_path / "pukaar-model-2b.litertlm"))

    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: (_ for _ in ()).throw(ModuleNotFoundError("litert_lm")))

    health = runtime.health()

    assert health.enabled is True
    assert health.reachable is False
    assert health.provider == "litert"
    assert "litert_lm" in health.detail


def test_litert_runtime_generate_text_uses_engine(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "pukaar-model-2b.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(model_path))
    monkeypatch.setenv("PUKAAR_NODE_BACKEND", "cpu")
    monkeypatch.setenv("PUKAAR_NODE_VISION_BACKEND", "gpu")

    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    calls: list[dict[str, object]] = []

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, message):
            calls.append({"message": message})
            return {"content": [{"text": "respuesta LiteRT"}]}

    class FakeEngine:
        def __init__(self, model_path, **kwargs):
            calls.append({"model_path": model_path, "kwargs": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    result = runtime.generate_text("system prompt", "user prompt", max_tokens=128)

    assert result == "respuesta LiteRT"
    assert any(entry.get("model_path") == str(model_path) for entry in calls)
    assert any(
        entry.get("kwargs") == {
            "backend": "cpu",
            "cache_dir": str(tmp_path / "litert-cache"),
            "max_num_tokens": 1024,
            "enable_speculative_decoding": True,
        }
        for entry in calls
    )
    assert any("user prompt" in str(entry.get("message")) for entry in calls)


def test_litert_runtime_generate_multimodal_json(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "pukaar-model-2b.litertlm"
    model_path.write_bytes(b"fake-model")
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-image")

    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(model_path))
    monkeypatch.setenv("PUKAAR_NODE_BACKEND", "cpu")
    monkeypatch.setenv("PUKAAR_NODE_VISION_BACKEND", "gpu")

    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, message):
            assert isinstance(message, dict)
            assert any(part.get("type") == "image" for part in message["content"])
            return {
                "content": [
                    {
                        "text": '{"description_es":"Agua alta","water_visible":true,"infrastructure_at_risk":true,"confidence":0.8}'
                    }
                ]
            }

    class FakeEngine:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    result = runtime.generate_multimodal_json(
        "system prompt",
        "describe la escena",
        [image_path],
        max_tokens=128,
    )

    assert result is not None
    assert result["description_es"] == "Agua alta"


def test_litert_runtime_uses_separate_multimodal_engine(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "pukaar-model-2b.litertlm"
    model_path.write_bytes(b"fake-model")
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-image")

    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(model_path))
    monkeypatch.setenv("PUKAAR_NODE_BACKEND", "gpu")
    monkeypatch.setenv("PUKAAR_NODE_VISION_BACKEND", "cpu")
    monkeypatch.setenv("PUKAAR_NODE_MULTIMODAL_BACKEND", "cpu")
    monkeypatch.setenv("PUKAAR_NODE_MULTIMODAL_VISION_BACKEND", "cpu")
    monkeypatch.setenv("PUKAAR_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS", "2048")

    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    calls: list[dict[str, object]] = []

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            return {"content": [{"text": '{"status":"ok"}'}]}

    class FakeEngine:
        def __init__(self, model_path, **kwargs):
            calls.append({"model_path": model_path, "kwargs": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") == '{"status":"ok"}'
    runtime.generate_multimodal_json("system prompt", "user prompt", [image_path])

    assert calls[0]["kwargs"]["backend"] == "gpu"
    assert calls[0]["kwargs"]["max_num_tokens"] == 1024
    assert "vision_backend" not in calls[0]["kwargs"]
    assert calls[1]["kwargs"]["backend"] == "cpu"
    assert calls[1]["kwargs"]["vision_backend"] == "cpu"
    assert calls[1]["kwargs"]["max_num_tokens"] == 2048


def test_litert_runtime_honors_speculative_decoding_override(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "pukaar-model-2b.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(model_path))
    monkeypatch.setenv("PUKAAR_NODE_ENABLE_SPECULATIVE_DECODING", "false")

    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    calls: list[dict[str, object]] = []

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            return {"content": [{"text": "ok"}]}

    class FakeEngine:
        def __init__(self, _model_path, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") == "ok"
    assert calls[0]["backend"] == "gpu"
    assert calls[0]["enable_speculative_decoding"] is False


def test_litert_runtime_repairs_truncated_json_object():
    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    raw = (
        '{"assessment_level":"green",'
        '"critical_evidence":{"confidence":0.8}'
    )

    parsed = LiteRTNodeRuntime._extract_json(raw)

    assert parsed == {
        "assessment_level": "green",
        "critical_evidence": {"confidence": 0.8},
    }


def test_litert_runtime_returns_none_when_dependency_is_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(tmp_path / "pukaar-model-2b.litertlm"))

    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: (_ for _ in ()).throw(ModuleNotFoundError("litert_lm")))

    assert runtime.generate_text("system prompt", "user prompt") is None


def test_litert_runtime_exposes_last_send_error(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "pukaar-model-2b.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(model_path))

    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            raise RuntimeError("litert_lm_conversation_send_message failed")

    class FakeEngine:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") is None
    assert runtime.last_error_type == "RuntimeError"
    assert runtime.last_error_detail == "litert_lm_conversation_send_message failed"


def test_litert_runtime_resets_engine_and_retries_reuse_failure(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "pukaar-model-2b.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(model_path))

    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    calls: list[str] = []

    class FakeConversation:
        def __init__(self, label: str):
            self.label = label

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            calls.append(self.label)
            if self.label == "engine-1":
                raise RuntimeError("litert_lm_conversation_send_message failed")
            return {"content": [{"text": "retry ok"}]}

    class FakeEngine:
        counter = 0

        def __init__(self, *_args, **_kwargs):
            type(self).counter += 1
            self.label = f"engine-{type(self).counter}"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation(self.label)

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") == "retry ok"
    assert calls == ["engine-1", "engine-2"]
    assert FakeEngine.counter == 2
    assert runtime.last_error_type is None
    assert runtime.last_error_detail is None
    assert runtime.last_response_type == "dict"


def test_litert_runtime_returns_none_when_reuse_retry_fails(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "pukaar-model-2b.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(model_path))

    from Pukaar.adapters.litert_node import LiteRTNodeRuntime

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            raise RuntimeError("litert_lm_conversation_send_message failed")

    class FakeEngine:
        counter = 0

        def __init__(self, *_args, **_kwargs):
            type(self).counter += 1

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") is None
    assert FakeEngine.counter == 2
    assert runtime.last_error_type == "RuntimeError"
    assert runtime.last_error_detail == "litert_lm_conversation_send_message failed"
