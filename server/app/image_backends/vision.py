"""Vision backend — multimodal LLM classifies the image directly.

Sends the image (base64-encoded) and a structured prompt to a vision-capable
model via Ollama (e.g. ``qwen2-vl:7b``, ``llava``). Useful for real photos
where there's no readable text — the model looks at visual content and decides.
"""

from __future__ import annotations

import base64

from ..ollama_client import OllamaClient
from ..prompt import parse_model_output
from .base import ImageClassifyResult, ImageProcessor

# The prompt is deliberately explicit about the JSON schema. Vision LLMs are
# weaker on instruction-following than text LLMs of similar size, so being
# verbose here pays off in reliable parses.
VISION_PROMPT = """You are an image content classifier specialised in detecting offensive material in a Hebrew-language context.

Examine the image and consider:
- Any text visible in the image (especially Hebrew text) — read it carefully and judge whether the text content is offensive.
- Visual content — violence, gore, hateful symbols (e.g. Nazi imagery, hate-group symbols), explicit / sexual content, threats.
- Apparent intent — would a Hebrew speaker reasonably consider this image offensive?

Reply with ONLY a JSON object, no other text, in this exact shape:
{
  "is_offensive": true or false,
  "category": "abusive" | "hate" | "violence" | "pornographic" | "non_offensive",
  "confidence": a number between 0.0 and 1.0
}

Choose the single most specific category. Default to "non_offensive" if you are unsure or the image does not match any offensive category."""


class VisionBackend(ImageProcessor):
    """Send the image to a vision LLM and parse its JSON verdict."""

    def __init__(self, vision_ollama: OllamaClient):
        self.vision_ollama = vision_ollama

    async def process(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
    ) -> ImageClassifyResult:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        raw = await self.vision_ollama.generate_json(
            VISION_PROMPT,
            images_b64=[b64],
        )
        parsed = parse_model_output(raw)
        return ImageClassifyResult(
            is_offensive=parsed["is_offensive"],
            category=parsed["category"],
            confidence=parsed["confidence"],
            extracted_text="",  # vision backend doesn't extract text
            backend="vision",
            strategy="vision",
        )
