from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

GenerationKind = Literal["image", "video"]
GenerationMode = Literal["text2image", "image2image", "text2video", "image2video"]
GenerationStatus = Literal["pending", "running", "success", "failed", "timeout", "unknown"]


@dataclass
class GenerationRequest:
    provider: str
    kind: GenerationKind
    mode: GenerationMode
    prompt: str = ""
    size: str = ""
    image_b64: str = ""
    image_url: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationOutput:
    output_type: str
    url: str = ""
    file_path: str = ""
    mime_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    provider: str
    kind: GenerationKind
    mode: GenerationMode
    status: GenerationStatus
    task_id: str = ""
    outputs: list[GenerationOutput] = field(default_factory=list)
    fail_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def first_url(self, output_type: str) -> str:
        for item in self.outputs:
            if item.output_type == output_type and item.url:
                return item.url
        return ""
