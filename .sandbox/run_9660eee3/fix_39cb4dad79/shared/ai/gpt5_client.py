from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Model response did not contain a JSON object: {text[:200]}")
    return json.loads(cleaned[start : end + 1])


def _image_content(path: Path) -> dict[str, str]:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:image/png;base64,{data}",
    }


class OpenAIJsonClient:
    def __init__(self, model: str = "gpt-5", reasoning_effort: str | None = "medium") -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for live OpenAI model runners.")

        from openai import OpenAI

        self._client = OpenAI()
        self._model = model
        self._reasoning_effort = reasoning_effort

    def create_json(
        self,
        *,
        instructions: str,
        prompt: str,
        image_paths: list[Path] | None = None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for image_path in image_paths or []:
            content.append(_image_content(image_path))

        request: dict[str, Any] = {
            "model": self._model,
            "instructions": instructions,
            "input": [{"role": "user", "content": content}],
        }
        if self._reasoning_effort:
            request["reasoning"] = {"effort": self._reasoning_effort}

        response = self._client.responses.create(**request)
        return _extract_json(response.output_text)


GPT5JsonClient = OpenAIJsonClient
