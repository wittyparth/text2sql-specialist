"""Prime each server's prompt cache with every preset schema so the first real question is fast."""

import logging
import threading

from ..prompt import build_messages
from .core import Backend
from .databases import Preset

log = logging.getLogger("app.warmup")


class WarmupState:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.detail = "starting"


def wait_for_servers(backends: list[Backend], state: WarmupState, tries: int = 90) -> list[Backend]:
    alive: list[Backend] = []
    for _ in range(tries):
        alive = [b for b in backends if b.client.healthy()]
        if len(alive) == len(backends):
            break
        state.detail = "waiting for model servers"
        threading.Event().wait(2)
    return alive


def warm(backends: list[Backend], presets: dict[str, Preset], state: WarmupState) -> None:
    alive = wait_for_servers(backends, state)
    for backend in alive:
        for preset in presets.values():
            state.detail = f"warming {backend.name} on {preset.label}"
            # same system + schema prefix as a real request; only the question differs
            backend.client.complete(build_messages(preset.schema, "warm up"), max_tokens=1)
    log.info("warmup done for %s", [b.name for b in alive])
    state.detail = "ready"
    state.ready.set()


def start_in_background(backends, presets, state: WarmupState) -> None:
    threading.Thread(target=warm, args=(backends, presets, state), daemon=True).start()
