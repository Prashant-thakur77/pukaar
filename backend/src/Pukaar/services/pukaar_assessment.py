from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from PIL import Image, ImageOps

from Pukaar.core.settings import get_settings
from Pukaar.models.domain import Site, SiteCalibration
from Pukaar.services.deterministic_firewall import FirewallResult, analyze_frames
from Pukaar.services.storage import get_upload_dir, persist_json_artifact


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class EvidenceFrame:
    frame_path: str
    timestamp_s: float
    brightness: float
    contrast: float
    motion_score: float
    edge_strength: float
    waterline_ratio_hint: float
    waterline_y: int


@dataclass
class AssessmentArtifactPack:
    manifest_path: str
    selected_frame_paths: list[str]
    evidence_frame_path: str


@dataclass
class AssessmentVerdict:
    assessment_level: str
    assessment_score: float
    temporal_summary: str
    reasoning_summary: str
    reasoning_steps: list[str]
    critical_evidence: dict[str, Any]
    runner_name: str
    runner_mode: str
    fallback_used: bool


@dataclass
class TemporalEvidencePack:
    site_id: str
    site_name: str
    site_region: str
    video_path: str
    source_type: str
    started_at: datetime
    ended_at: datetime
    frames_analyzed: int
    selected_frames: list[EvidenceFrame]
    evidence_frame_path: str
    reference_y: float
    critical_y: float
    summary_metrics: dict[str, Any]
    artifact_pack: AssessmentArtifactPack


@dataclass
class PukaarAssessment:
    evidence_pack: TemporalEvidencePack
    verdict: AssessmentVerdict
    waterline_ratio_hint: float
    rise_velocity_hint: float
    crossed_critical_line_hint: bool
    confidence: float
    decision_trace: list[str]


class PukaarAIAssessmentRunner(Protocol):
    def assess(self, pack: TemporalEvidencePack) -> AssessmentVerdict | None: ...


def _level_from_score(score: float) -> str:
    if score >= 0.82:
        return "red"
    if score >= 0.62:
        return "orange"
    if score >= 0.4:
        return "yellow"
    return "green"


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "si", "sí"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return default


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _optimize_frame(source: Path, *, max_side: int, prefix: str) -> str:
    target = get_upload_dir() / f"{prefix}-{uuid4().hex}.jpg"
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if max_side > 0:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        image.save(target, format="JPEG", quality=82, optimize=True)
    return str(target)


def _run_ffmpeg_extract(video_path: Path, output_dir: Path, *, max_frames: int, sample_seconds: int, max_side: int) -> list[Path]:
    ffmpeg_setting = get_settings().ffmpeg_bin
    ffmpeg = shutil.which(ffmpeg_setting) or (ffmpeg_setting if Path(ffmpeg_setting).exists() else None)
    if ffmpeg is None:
        raise ValueError("ffmpeg is required for multimodal-only video frame extraction; set PUKAAR_FFMPEG_BIN if it is not on PATH")

    interval = max(1, int(sample_seconds))
    scale = (
        f"scale='if(gt(iw,ih),min({max_side},iw),-2)':"
        f"'if(gt(ih,iw),min({max_side},ih),-2)'"
    )
    output_pattern = output_dir / "pukaar-frame-%03d.png"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps=1/{interval},{scale}",
        "-frames:v",
        str(max(1, max_frames)),
        str(output_pattern),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown ffmpeg error").strip()
        raise ValueError(f"ffmpeg frame extraction failed: {detail}")
    extracted = sorted(output_dir.glob("pukaar-frame-*.png"))
    if extracted:
        return extracted

    fallback_command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        scale,
        "-frames:v",
        "1",
        str(output_pattern),
    ]
    fallback = subprocess.run(fallback_command, capture_output=True, text=True, check=False)
    if fallback.returncode != 0:
        detail = (fallback.stderr or fallback.stdout or "unknown ffmpeg error").strip()
        raise ValueError(f"ffmpeg frame extraction fallback failed: {detail}")
    return sorted(output_dir.glob("pukaar-frame-*.png"))


class MultimodalEvidenceBuilder:
    """Prepares image evidence for Pukaar AI without OpenCV or numeric CV analysis."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def build(
        self,
        site: Site,
        video_path: str,
        calibration: SiteCalibration | None,
        source_type: str,
    ) -> tuple[TemporalEvidencePack, float, float, bool, float, list[str]]:
        source_path = Path(video_path)
        if not source_path.exists():
            raise ValueError(f"Could not open source media: {video_path}")

        selected_paths: list[str] = []
        source_frames: list[Path]
        sample_seconds = self.settings.pukaar_multimodal_frame_sample_seconds
        max_frames = max(1, self.settings.pukaar_multimodal_max_frames)

        if source_path.suffix.lower() in IMAGE_SUFFIXES:
            source_frames = [source_path]
        else:
            with tempfile.TemporaryDirectory(prefix="pukaar-ffmpeg-") as tmp:
                extracted = _run_ffmpeg_extract(
                    source_path,
                    Path(tmp),
                    max_frames=max_frames,
                    sample_seconds=sample_seconds,
                    max_side=self.settings.pukaar_multimodal_image_max_side,
                )
                if not extracted:
                    raise ValueError("No frames could be extracted from source media")
                source_frames = [Path(path) for path in extracted]
                for index, frame_path in enumerate(source_frames, start=1):
                    selected_paths.append(
                        _optimize_frame(
                            frame_path,
                            max_side=self.settings.pukaar_multimodal_image_max_side,
                            prefix=f"pukaar-mm-frame-{index}",
                        )
                    )

        if not selected_paths:
            for index, frame_path in enumerate(source_frames[:max_frames], start=1):
                selected_paths.append(
                    _optimize_frame(
                        frame_path,
                        max_side=self.settings.pukaar_multimodal_image_max_side,
                        prefix=f"pukaar-mm-frame-{index}",
                    )
                )

        firewall: FirewallResult = analyze_frames(selected_paths, float(sample_seconds))

        selected_frames: list[EvidenceFrame] = []
        dimensions: list[dict[str, int]] = []
        for index, frame_path in enumerate(selected_paths, start=1):
            width, height = _image_size(Path(frame_path))
            dimensions.append({"width": width, "height": height})
            fm = firewall.frames[index - 1] if index - 1 < len(firewall.frames) else None
            selected_frames.append(
                EvidenceFrame(
                    frame_path=frame_path,
                    timestamp_s=round((index - 1) * sample_seconds, 2),
                    brightness=fm.brightness if fm else -1.0,
                    contrast=fm.contrast if fm else -1.0,
                    motion_score=fm.motion_score if fm else -1.0,
                    edge_strength=fm.edge_strength if fm else -1.0,
                    waterline_ratio_hint=fm.waterline_ratio if fm else -1.0,
                    waterline_y=fm.waterline_y if fm else -1,
                )
            )

        ended_at = datetime.utcnow()
        duration_seconds = max(float((len(selected_frames) - 1) * sample_seconds), 1.0)
        started_at = ended_at - timedelta(seconds=duration_seconds)
        evidence_frame_path = selected_paths[-1]
        summary_metrics = {
            "mode": "pukaar-ai4-multimodal-with-firewall" if firewall.opencv_used else "pukaar-ai4-multimodal-only",
            "opencv_used": firewall.opencv_used,
            "source_media": str(source_path),
            "sample_seconds": sample_seconds,
            "requested_frames": max_frames,
            "selected_curated_frames": len(selected_frames),
            "image_max_side": self.settings.pukaar_multimodal_image_max_side,
            "frame_dimensions": dimensions,
            "calibration_available": calibration is not None,
            "calibration_notes": getattr(calibration, "notes", None),
            "profile": self.settings.pukaar_node_profile,
            "deterministic_prefilter": firewall.to_dict(include_frames=False),
        }
        trace = [
            "multimodal pipeline selected",
            f"extracted {len(selected_frames)} frame(s)",
            f"deterministic firewall: opencv_used={firewall.opencv_used} "
            f"waterline_ratio={firewall.waterline_ratio:.3f} "
            f"rise_velocity={firewall.rise_velocity:+.4f}/s "
            f"water_level={firewall.water_level} crossed={firewall.crossed_critical_line}",
            f"optimized frames to max_side={self.settings.pukaar_multimodal_image_max_side}px",
            "Pukaar AI multimodal consumes frames plus firewall vector for visual interpretation",
        ]
        pack = TemporalEvidencePack(
            site_id=site.id,
            site_name=site.name,
            site_region=site.region,
            video_path=video_path,
            source_type=source_type,
            started_at=started_at,
            ended_at=ended_at,
            frames_analyzed=len(selected_frames),
            selected_frames=selected_frames,
            evidence_frame_path=evidence_frame_path,
            reference_y=0.0,
            critical_y=0.0,
            summary_metrics=summary_metrics,
            artifact_pack=AssessmentArtifactPack(
                manifest_path="",
                selected_frame_paths=selected_paths,
                evidence_frame_path=evidence_frame_path,
            ),
        )
        return (
            pack,
            firewall.waterline_ratio,
            firewall.rise_velocity,
            firewall.crossed_critical_line,
            firewall.confidence,
            trace,
        )


class PukaarAssessmentEngine:
    def __init__(
        self,
        builder: MultimodalEvidenceBuilder,
        runner: PukaarAIAssessmentRunner,
    ) -> None:
        self.builder = builder
        self.runner = runner

    def assess_video(
        self,
        site: Site,
        video_path: str,
        calibration: SiteCalibration | None,
        source_type: str,
    ) -> PukaarAssessment:
        pack, ratio_hint, rise_velocity_hint, crossed_hint, confidence, trace = self.builder.build(
            site=site,
            video_path=video_path,
            calibration=calibration,
            source_type=source_type,
        )
        firewall_block = pack.summary_metrics.get("deterministic_prefilter", {})
        verdict = self.runner.assess(pack)
        if verdict is None:
            verdict = self._fallback_verdict(pack)
            trace.append("Pukaar AI multimodal runner unavailable or invalid; emitted conservative unknown fallback")
        else:
            trace.append(f"Pukaar AI runner {verdict.runner_mode} produced {verdict.assessment_level}")
            ratio_hint = _safe_float(verdict.critical_evidence.get("waterline_ratio"), ratio_hint)
            rise_velocity_hint = _safe_float(verdict.critical_evidence.get("rise_velocity"), rise_velocity_hint)
            crossed_hint = _safe_bool(verdict.critical_evidence.get("crossed_critical_line"), crossed_hint)
            confidence = _safe_float(verdict.critical_evidence.get("confidence"), verdict.assessment_score)
        if firewall_block:
            verdict.critical_evidence.setdefault("deterministic_prefilter", firewall_block)

        manifest_payload = {
            "bundle": self._serialize_pack(pack),
            "verdict": asdict(verdict),
            "decision_trace": trace,
        }
        manifest_path = persist_json_artifact(manifest_payload, "pukaar-assessment")
        pack.artifact_pack.manifest_path = manifest_path

        return PukaarAssessment(
            evidence_pack=pack,
            verdict=verdict,
            waterline_ratio_hint=max(0.0, min(1.0, ratio_hint)),
            rise_velocity_hint=rise_velocity_hint,
            crossed_critical_line_hint=crossed_hint,
            confidence=max(0.0, min(1.0, confidence)),
            decision_trace=trace,
        )

    def _fallback_verdict(self, pack: TemporalEvidencePack) -> AssessmentVerdict:
        return AssessmentVerdict(
            assessment_level="yellow",
            assessment_score=0.42,
            temporal_summary=(
                f"Pukaar preparo {len(pack.selected_frames)} frame(s) para Pukaar AI multimodal, "
                "pero el modelo no devolvio una respuesta valida."
            ),
            reasoning_summary=(
                "Sin interpretacion visual del modelo no se infiere nivel de agua. "
                "Se emite un estado preventivo bajo revision manual."
            ),
            reasoning_steps=[
                "frames preparados sin OpenCV",
                "Pukaar AI multimodal no disponible",
                "mantener revision manual",
            ],
            critical_evidence={
                "selected_frames": len(pack.selected_frames),
                "evidence_frame_path": pack.evidence_frame_path,
                "confidence": 0.0,
                "waterline_ratio": 0.0,
                "crossed_critical_line": False,
            },
            runner_name="pukaar-no-model",
            runner_mode="multimodal-unavailable-fallback",
            fallback_used=True,
        )

    @staticmethod
    def _serialize_pack(pack: TemporalEvidencePack) -> dict[str, Any]:
        return {
            "site_id": pack.site_id,
            "site_name": pack.site_name,
            "site_region": pack.site_region,
            "video_path": pack.video_path,
            "source_type": pack.source_type,
            "started_at": pack.started_at.isoformat(),
            "ended_at": pack.ended_at.isoformat(),
            "frames_analyzed": pack.frames_analyzed,
            "selected_frames": [asdict(frame) for frame in pack.selected_frames],
            "evidence_frame_path": pack.evidence_frame_path,
            "reference_y": pack.reference_y,
            "critical_y": pack.critical_y,
            "summary_metrics": pack.summary_metrics,
            "artifact_pack": asdict(pack.artifact_pack),
        }

    @staticmethod
    def bundle_json(pack: TemporalEvidencePack) -> str:
        return json.dumps(PukaarAssessmentEngine._serialize_pack(pack), ensure_ascii=True)


TemporalEvidenceBuilder = MultimodalEvidenceBuilder
