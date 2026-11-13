"""Minimal OpenAI-compatible chat client: llama-server, Ollama and OpenRouter all speak this."""

import time
from dataclasses import dataclass

import httpx

BACKOFF_S = (1, 4, 16)


@dataclass
class Completion:
    text: str = ""
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None  # set only when every retry failed


class ChatClient:
    def __init__(
        self,
        url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 120,
        backoff: tuple[float, ...] = BACKOFF_S,
    ):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.Client(base_url=url.rstrip("/"), headers=headers, timeout=timeout_s)
        self.model = model
        self.backoff = backoff

    def complete(
        self,
        messages: list[dict],
        max_tokens: int = 256,
        temperature: float = 0.0,
        seed: int | None = 0,
        sleep=time.sleep,
    ) -> Completion:
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stop": ["<|im_end|>"],
        }
        if seed is not None:
            body["seed"] = seed
        last = ""
        for attempt, delay in enumerate(self.backoff, start=1):
            started = time.monotonic()
            try:
                resp = self.http.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage") or {}
                return Completion(
                    text=data["choices"][0]["message"]["content"] or "",
                    latency_s=time.monotonic() - started,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                last = f"{type(exc).__name__}: {exc}"
                if attempt < len(self.backoff):
                    sleep(delay)
        return Completion(error=last)

    def healthy(self) -> bool:
        """llama-server answers /health at the root; Ollama and OpenRouter list /models."""
        root = str(self.http.base_url).rstrip("/").removesuffix("/v1")
        for url in (f"{root}/health", str(self.http.base_url) + "/models"):
            try:
                if self.http.get(url).status_code == 200:
                    return True
            except httpx.HTTPError:
                continue
        return False
