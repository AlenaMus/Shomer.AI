from __future__ import annotations

import httpx


class OllamaClient:
    """Async client wrapping Ollama's ``/api/generate`` endpoint.

    One instance per model: the constructor binds a model name so callers
    don't have to specify it on every call. For multimodal (vision) use,
    pass ``images_b64`` to :meth:`generate_json`.
    """

    def __init__(self, base_url: str, model: str, timeout_s: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def is_alive(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/api/tags")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def generate_json(
        self,
        user_prompt: str,
        images_b64: list[str] | None = None,
    ) -> str:
        """Call ``/api/generate`` with ``format=json`` so the model returns valid JSON.

        Pass ``images_b64`` (list of base64-encoded image bytes, no data: prefix)
        to send a multimodal request — the model must be a vision-capable one
        (e.g. ``qwen2-vl:7b``, ``llava``). For text-only models, leave it out.
        """
        payload: dict = {
            "model": self.model,
            "prompt": user_prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1, "top_p": 0.9},
        }
        if images_b64:
            payload["images"] = images_b64
        r = await self._client.post(f"{self.base_url}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
        return data.get("response", "")
