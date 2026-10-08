from __future__ import annotations

import importlib.util
import logging
from datetime import datetime
from pathlib import Path

import anyio
import httpx
import pytest

from Pukaar.adapters.image_assessment import Pukaar AIImageAssessmentAdapter
from Pukaar.adapters.litert_node import LiteRTNodeHealth, LiteRTNodeRuntime
from Pukaar.adapters.llm import LLMHealth
from Pukaar.adapters.video_assessment import LiteRTPukaar AIRunner, OllamaPukaar AIRunner
from Pukaar.api import deps as deps_module
from Pukaar.api.routers.runtime import get_runtime_status
from Pukaar.core import settings as settings_module
from Pukaar.services.pukaar_assessment import AssessmentArtifactPack, EvidenceFrame, TemporalEvidencePack


@pytest.fixture(autouse=True)
def clear_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


def _pack(image_path: Path) -> TemporalEvidencePack:
    return TemporalEvidencePack(
        site_id="test-site",
        site_name="Puente Test",
        site_region="Zona Demo",
        video_path=str(image_path),
        source_type="frame",
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
        frames_analyzed=1,
        selected_frames=[
            EvidenceFrame(
                frame_path=str(image_path),
                timestamp_s=0.0,
                brightness=-1.0,
                contrast=-1.0,
                motion_score=-1.0,
                edge_strength=-1.0,
                waterline_ratio_hint=-1.0,
                waterline_y=-1,
            )
        ],
        evidence_frame_path=str(image_path),
        reference_y=0,
        critical_y=0,
        summary_metrics={"mode": "pukaar-ai4-multimodal-only"},
        artifact_pack=AssessmentArtifactPack(
            manifest_path="manifest.json",
            selected_frame_paths=[str(image_path)],
            evidence_frame_path=str(image_path),
        ),
    )


def test_deps_select_litert_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(tmp_path / "pukaar-model-2b.litertlm"))

    runner, assessor = deps_module._build_pukaar_runtime_components()

    assert isinstance(runner, LiteRTPukaar AIRunner)
    assert isinstance(assessor, Pukaar AIImageAssessmentAdapter)
    assert assessor.runtime is deps_module.pukaar_node_runtime
    assert assessor.force_embedded is True


def test_deps_select_ollama_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "ollama")

    runner, assessor = deps_module._build_pukaar_runtime_components()

    assert isinstance(runner, OllamaPukaar AIRunner)
    assert isinstance(assessor, Pukaar AIImageAssessmentAdapter)
    assert assessor.runtime is None
    assert assessor.force_embedded is False


def test_deps_select_litert_decision_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    settings_module.get_settings.cache_clear()

    assert deps_module.get_decision_runtime() is deps_module.pukaar_node_runtime


def test_deps_select_ollama_decision_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "ollama")
    settings_module.get_settings.cache_clear()

    assert deps_module.get_decision_runtime() is deps_module.llm_client


def test_invalid_pukaar_provider_fails_startup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "bad-provider")
    settings_module.get_settings.cache_clear()
    spec = importlib.util.spec_from_file_location(
        "Pukaar.api._deps_invalid_test",
        Path(deps_module.__file__),
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    with pytest.raises(ValueError, match="Unsupported PUKAAR_NODE_PROVIDER"):
        spec.loader.exec_module(module)


def test_ollama_provider_runner_returns_verdict(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    image_path = tmp_path / "synthetic.jpg"
    image_path.write_bytes(b"fake-image")
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "ollama")
    monkeypatch.setenv("PUKAAR_LLM_ENABLED", "true")
    monkeypatch.setenv("PUKAAR_MULTIMODAL_ENABLED", "true")
    monkeypatch.setenv("PUKAAR_MULTIMODAL_MODEL", "pukaar-model:2b")
    monkeypatch.setenv("PUKAAR_MULTIMODAL_BASE_URL", "http://127.0.0.1:11434/v1")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "message": {
                    "content": (
                        '{"assessment_level":"orange","assessment_score":0.76,'
                        '"temporal_summary":"La imagen muestra agua alta junto al puente.",'
                        '"reasoning_summary":"Pukaar AI detecta ocupacion del cauce y riesgo sobre infraestructura.",'
                        '"reasoning_steps":["mirar linea de agua","comparar con puente","escalar"],'
                        '"critical_evidence":{"waterline_ratio":0.76,"crossed_critical_line":false,'
                        '"rise_velocity":0.0,"confidence":0.82,"visual_cues":["agua alta"]}}'
                    )
                }
            }

    def fake_post(self, *_args, **_kwargs):
        return FakeResponse()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(
        "Pukaar.adapters.video_assessment._encode_image",
        lambda *_args, **_kwargs: "encoded",
    )

    runner, _assessor = deps_module._build_pukaar_runtime_components()
    assert isinstance(runner, OllamaPukaar AIRunner)
    verdict = runner.assess(_pack(image_path))

    assert verdict is not None
    assert verdict.runner_mode == "ollama-multimodal-temporal"
    assert verdict.fallback_used is False


def test_runtime_status_uses_ollama_health_for_dev_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "ollama")
    monkeypatch.setattr(
        deps_module.llm_client,
        "health",
        lambda: LLMHealth(True, True, "http://127.0.0.1:11434/v1", "pukaar-model:2b", "ok"),
    )
    monkeypatch.setattr(
        deps_module.pukaar_node_runtime,
        "health",
        lambda: LiteRTNodeHealth(
            enabled=False,
            reachable=False,
            provider="ollama",
            backend="cpu",
            model="pukaar-model:2b",
            model_path="embedded://ollama-dev",
            detail="Pukaar node provider is not litert",
        ),
    )

    status = anyio.run(get_runtime_status)

    assert status.pukaar["provider"] == "ollama"
    assert status.pukaar["engine_ready"] is True
    assert status.pukaar["counts_for_p1"] is False
    assert status.pukaar["p1_runtime_ready"] is False
    assert "runner.mode=litert-multimodal-temporal" in status.pukaar["p1_evidence_required"]
    assert "Ollama development runtime" in status.pukaar["engine_detail"]


def test_runtime_status_exposes_litert_p1_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    model_path = tmp_path / "pukaar-model-2b.litertlm"
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(model_path))
    monkeypatch.setenv("PUKAAR_NODE_BACKEND", "gpu")
    monkeypatch.setenv("PUKAAR_NODE_ENABLE_SPECULATIVE_DECODING", "true")
    monkeypatch.setattr(
        deps_module.pukaar_node_runtime,
        "health",
        lambda: LiteRTNodeHealth(
            enabled=True,
            reachable=True,
            provider="litert",
            backend="gpu",
            model="pukaar-model-2b.litertlm",
            model_path=str(model_path),
            detail="ready",
        ),
    )

    status = anyio.run(get_runtime_status)

    assert status.pukaar["provider"] == "litert"
    assert status.pukaar["backend"] == "gpu"
    assert status.pukaar["multimodal_backend"] == "cpu"
    assert status.pukaar["multimodal_vision_backend"] == "cpu"
    assert status.pukaar["speculative_decoding"] is True
    assert status.pukaar["max_output_tokens"] == 1024
    assert status.pukaar["multimodal_max_output_tokens"] == 2048
    assert status.pukaar["engine_ready"] is True
    assert status.pukaar["counts_for_p1"] is True
    assert status.pukaar["p1_runtime_ready"] is True
    assert "Runtime readiness only" in status.pukaar["p1_evidence_required"]


def test_litert_runtime_logs_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture):
    monkeypatch.setenv("PUKAAR_NODE_PROVIDER", "litert")
    monkeypatch.setenv("PUKAAR_NODE_MODEL_PATH", str(tmp_path / "pukaar-model-2b.litertlm"))
    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_ensure_engine", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with caplog.at_level(logging.WARNING):
        response = runtime.generate_text("sys", "user", max_tokens=32)

    assert response is None
    assert "LiteRT node message failed" in caplog.text


def test_productive_scripts_keep_litert_gpu_speculative_defaults():
    root = Path(__file__).resolve().parents[2]
    script_paths = [
        root / "scripts" / "run_pukaar_pi8_multimodal_demo.sh",
        root / "scripts" / "run_pukaar_pi16_multimodal_prod.sh",
    ]

    for script_path in script_paths:
        text = script_path.read_text(encoding="utf-8")
        assert 'PUKAAR_NODE_PROVIDER="${PUKAAR_NODE_PROVIDER:-litert}"' in text
        assert 'PUKAAR_NODE_BACKEND="${PUKAAR_NODE_BACKEND:-gpu}"' in text
        assert 'PUKAAR_NODE_MULTIMODAL_BACKEND="${PUKAAR_NODE_MULTIMODAL_BACKEND:-cpu}"' in text
        assert 'PUKAAR_NODE_MULTIMODAL_VISION_BACKEND="${PUKAAR_NODE_MULTIMODAL_VISION_BACKEND:-cpu}"' in text
        assert 'PUKAAR_NODE_ENABLE_SPECULATIVE_DECODING="${PUKAAR_NODE_ENABLE_SPECULATIVE_DECODING:-true}"' in text
        assert 'PUKAAR_NODE_MAX_OUTPUT_TOKENS="${PUKAAR_NODE_MAX_OUTPUT_TOKENS:-1024}"' in text
        assert 'PUKAAR_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS="${PUKAAR_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS:-2048}"' in text
        assert 'PUKAAR_LLM_ENABLED="${PUKAAR_LLM_ENABLED:-false}"' in text
        assert 'PUKAAR_MULTIMODAL_MODEL="${PUKAAR_MULTIMODAL_MODEL:-pukaar-model-2b.litertlm}"' in text
