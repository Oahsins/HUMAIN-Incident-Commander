"""One model-call interface for the agent. Credentials stay in environment variables.

Ported from the 29 Oct scaffold's src/llm.py (written by Codex) and extended with
a system prompt, multi-turn messages, JSON answers (structured outputs where the
provider has them), retries, a replay provider for runs without a key, a mock
provider for tests, and recording.

Models are named "provider:model":
    anthropic:<model>            needs ANTHROPIC_API_KEY
    openai:<model>               needs OPENAI_API_KEY
    lmstudio:<model>             a local LM Studio server (LM_STUDIO_BASE_URL, default http://localhost:1234/v1)
    replay:<file.jsonl>          answers recorded earlier with IC_RECORD=<file.jsonl>, in order
    mock:<name>                  a Python function registered with register_mock() (tests)
The default is the IC_MODEL environment variable, else DEFAULT_MODEL below
(configs/models.json lists the project's choices).
IC_EFFORT (low, medium, high) overrides the reasoning effort for every call.

Every call returns telemetry (provider, model, tokens, latency, estimated cost).
Unknown values stay None rather than pretending a call was free.
"""

import json
import math
import os
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
PRICES = ROOT / "configs" / "prices.json"
DEFAULT_MODEL = "anthropic:claude-opus-5-5"
ANTHROPIC_VERSION = "2026-10-21"
FALLBACK_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")   # models that take server-side refusal fallbacks


class ModelError(RuntimeError):
    """Safe error text: never includes provider bodies, prompts or credentials. `.call` holds the telemetry."""

    def __init__(self, message, call=None):
        super().__init__(message)
        self.call = call


def default_model():
    return os.environ.get("IC_MODEL") or DEFAULT_MODEL


def parse_model(name):
    name = name or default_model()
    if ":" not in name:
        raise ValueError(f"model must look like provider:model, got {name!r}")
    provider, model = name.split(":", 1)
    if provider not in ("anthropic", "openai", "lmstudio", "replay", "mock"):
        raise ValueError(f"unknown model provider {provider!r}")
    return provider, model


# ----- cost -----

def estimate_cost(provider, model, input_tokens, output_tokens, price_path=PRICES):
    """US dollars at standard token prices, or None when a price or a token count is unknown."""
    if input_tokens is None or output_tokens is None:
        return None
    try:
        rates = json.loads(Path(price_path).read_text(encoding="utf-8")).get("rates", {})
    except (OSError, ValueError):
        return None
    price = rates.get(f"{provider}:{model}") or rates.get(f"{provider}:*")
    if not price:
        return None
    rate_in, rate_out = price.get("input_usd_per_million"), price.get("output_usd_per_million")
    for rate in (rate_in, rate_out):
        if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0:
            return None
    return round((input_tokens * rate_in + output_tokens * rate_out) / 1_000_000, 6)


# ----- providers -----

def _post(url, payload, headers, timeout):
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json", **headers}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _anthropic(model, system, messages, max_tokens, schema, effort, timeout):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ModelError("ANTHROPIC_API_KEY is not set.")
    payload = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        payload["system"] = system
    output_config = {}
    if effort:
        output_config["effort"] = effort
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    if output_config:
        payload["output_config"] = output_config
    headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    if model in FALLBACK_MODELS:
        # If a safety classifier declines, the API retries on a suitable model inside the same call.
        payload["fallbacks"] = "default"
        headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
    response = _post("https://api.anthropic.com/v1/messages", payload, headers, timeout)
    usage = response.get("usage") or {}
    stop = response.get("stop_reason")
    if stop == "refusal":
        raise ModelError("The model declined this request (refusal).")
    if stop == "max_tokens":
        raise ModelError("The answer was cut off at the token limit.")
    text = "".join(block.get("text", "") for block in response.get("content", []) if block.get("type") == "text")
    return text, usage.get("input_tokens"), usage.get("output_tokens"), response.get("model") or model


def _openai(model, system, messages, max_tokens, schema, effort, timeout):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ModelError("OPENAI_API_KEY is not set.")
    payload = {"model": model, "input": messages, "max_output_tokens": max_tokens, "store": False}
    if system:
        payload["instructions"] = system
    response = _post("https://api.openai.com/v1/responses", payload, {"Authorization": f"Bearer {key}"}, timeout)
    if response.get("status") != "completed":
        raise ModelError("The OpenAI response was incomplete.")
    text = "".join(part.get("text", "") for item in response.get("output", []) if item.get("type") == "message"
                   for part in item.get("content", []) if part.get("type") == "output_text")
    usage = response.get("usage") or {}
    return text, usage.get("input_tokens"), usage.get("output_tokens"), response.get("model") or model


def _lmstudio(model, system, messages, max_tokens, schema, effort, timeout):
    base = (os.environ.get("LM_STUDIO_BASE_URL") or "http://localhost:1234/v1").rstrip("/")
    parsed = urlparse(base)
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.username or parsed.password:
        raise ModelError("LM Studio must be a plain local loopback URL without credentials.")
    headers = {}
    if os.environ.get("LM_STUDIO_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["LM_STUDIO_API_KEY"]
    chat = ([{"role": "system", "content": system}] if system else []) + messages
    response = _post(base + "/chat/completions", {"model": model, "messages": chat, "max_tokens": max_tokens},
                     headers, timeout)
    choice = response["choices"][0]
    if choice.get("finish_reason") not in ("stop", None):
        raise ModelError("The LM Studio answer was cut off.")
    usage = response.get("usage") or {}
    return (choice["message"]["content"] or "", usage.get("prompt_tokens"), usage.get("completion_tokens"),
            response.get("model") or model)


_MOCKS = {}
_REPLAYS = {}
_LOCK = threading.Lock()


def register_mock(name, fn):
    """fn(system, messages, schema, purpose) -> text. Used by tests through model="mock:<name>"."""
    _MOCKS[name] = fn


def _mock(model, system, messages, max_tokens, schema, effort, timeout, purpose=""):
    if model not in _MOCKS:
        raise ModelError(f"no mock model named {model}")
    return _MOCKS[model](system, messages, schema, purpose), None, None, model


def _replay(path, system, messages, max_tokens, schema, effort, timeout, purpose=""):
    """Answer with the next recorded answer for this purpose, so a recorded run can be watched without a key."""
    with _LOCK:
        state = _REPLAYS.get(path)
        if state is None:
            try:
                lines = Path(path).read_text(encoding="utf-8").splitlines()
            except OSError:
                raise ModelError(f"replay file not found: {path}") from None
            state = {"records": [json.loads(line) for line in lines if line.strip()], "used": set()}
            _REPLAYS[path] = state
        for index, record in enumerate(state["records"]):
            if index not in state["used"] and record.get("purpose") == purpose:
                state["used"].add(index)
                return record["text"], None, None, record.get("model", "replay")
    raise ModelError(f"the replay has no more recorded answers for {purpose or 'this call'}")


PROVIDERS = {"anthropic": _anthropic, "openai": _openai, "lmstudio": _lmstudio}


def _record(model_name, purpose, system, messages, text, call):
    path = os.environ.get("IC_RECORD")
    if not path:
        return
    with _LOCK:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)   # e.g. replays/ in a fresh clone
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": time.time(), "model": model_name, "purpose": purpose, "text": text,
                                     "call": call, "system_chars": len(system or ""),
                                     "messages": messages}) + "\n")


# ----- the one entry point -----

def complete(messages, *, system=None, model=None, max_tokens=16000, schema=None, effort=None, timeout=60.0,
             purpose="", retries=2):
    """Ask the model. Returns {"text", "json", "call"}; raises ModelError (with .call) on failure.

    messages: [{"role": "user" | "assistant", "content": str}, ...]
    schema:   a JSON schema for the answer. Anthropic enforces it (structured outputs);
              other providers are asked for JSON and the first JSON object in the text is parsed.
    """
    model_name = model or default_model()
    provider, name = parse_model(model_name)
    effort = os.environ.get("IC_EFFORT") or effort
    call = {"provider": provider, "model": name, "purpose": purpose, "input_tokens": None, "output_tokens": None,
            "latency_s": None, "estimated_cost_usd": None, "status": "failed", "error": None,
            "cost_basis": "standard API token prices; excludes hardware and other services"}
    started = time.perf_counter()
    text = None
    for attempt in range(retries + 1):
        try:
            if provider == "mock":
                text, tokens_in, tokens_out, used = _mock(name, system, messages, max_tokens, schema, effort, timeout,
                                                          purpose)
            elif provider == "replay":
                text, tokens_in, tokens_out, used = _replay(name, system, messages, max_tokens, schema, effort,
                                                            timeout, purpose)
            else:
                text, tokens_in, tokens_out, used = PROVIDERS[provider](name, system, messages, max_tokens, schema,
                                                                        effort, timeout)
            break
        except HTTPError as exc:
            retry_after = exc.headers.get("retry-after") if exc.headers else None
            if exc.code in (429, 500, 502, 503, 529) and attempt < retries:
                time.sleep(min(float(retry_after or 2 ** (attempt + 1)), 8.0))
                continue
            call["latency_s"] = round(time.perf_counter() - started, 3)
            call["error"] = f"http_{exc.code}"
            raise ModelError(f"Provider HTTP {exc.code}; check the key, the model name and limits.", call) from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries and not isinstance(exc, TimeoutError):
                time.sleep(2 ** attempt)
                continue
            call["latency_s"] = round(time.perf_counter() - started, 3)
            call["error"] = "timeout" if isinstance(exc, TimeoutError) else "unavailable"
            raise ModelError("Provider unavailable or the request timed out.", call) from None
        except ModelError as exc:
            call["latency_s"] = round(time.perf_counter() - started, 3)
            exc.call = call
            raise
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            call["latency_s"] = round(time.perf_counter() - started, 3)
            call["error"] = "unexpected_shape"
            raise ModelError("The provider's answer had an unexpected shape.", call) from None
    call.update(model=used, input_tokens=tokens_in, output_tokens=tokens_out,
                latency_s=round(time.perf_counter() - started, 3),
                estimated_cost_usd=(0.0 if provider in ("mock", "replay")
                                    else estimate_cost(provider, used, tokens_in, tokens_out)),
                status="ok")
    parsed = None
    if schema is not None:
        parsed = extract_json(text)
        if parsed is None:
            call["status"] = "invalid_output"
            call["error"] = "invalid_json"
            _record(model_name, purpose, system, messages, text, call)
            raise ModelError("The model did not answer with valid JSON.", call)
    _record(model_name, purpose, system, messages, text, call)
    return {"text": text, "json": parsed, "call": call}


def extract_json(text):
    """The JSON object in a model's answer: the whole text, a fenced block, or the first {...} span."""
    if not text:
        return None
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None
