"""Compatibility module for older imports.

The fixed Pukaar node no longer runs an OpenCV heuristic analyzer. Use
`services.pukaar_assessment.MultimodalEvidenceBuilder` plus the Pukaar AI
multimodal runner instead.
"""

from Pukaar.services.pukaar_assessment import PukaarAssessmentEngine, MultimodalEvidenceBuilder


__all__ = ["PukaarAssessmentEngine", "MultimodalEvidenceBuilder"]
