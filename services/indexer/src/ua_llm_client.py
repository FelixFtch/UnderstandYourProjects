#!/usr/bin/env python3
"""UA cloud/local analysis mode — enrichment-stage LLM client (2026-10-15).

Owner decision 2026-10-15: the qwen enrichment stage of the UYP indexing
pipeline (index_project.qwen_enrich, anchored_enrich.qwen,
project_digest.ollama_chat) may run either fully local (ollama qwen on
:11434, the default and historical behavior) or against a user-chosen cloud
provider ("UA 云端分析模式").  The Laya triage front-stage — the
key_file_classifier hard gates and laya_decide on :8901 — is ALWAYS local,
owner-pinned (业主钦定); it is never routed through this module.

Mode config (written 0600 by companion-api; this module only ever READS it):

  ~/dev/uyp/state/ua-cloud.json
  {"mode": "local"|"cloud",
   "provider": "qwen|openai|claude|gemini|deepseek|grok|muse|custom",
   "model": "<model name>",
   "base_url": "https://api.example/v1",
   "api_key_file": "~/.config/homehub/<provider>.key"}

Missing config, or mode != "cloud", -> load_client() returns None and every
caller keeps the byte-identical local ollama path.  A malformed config or a
missing/empty key raises CloudConfigError — an honest error that names paths,
never key material; callers warn and fall back to local.  The owner-facing
Studio path provisions the owner-only local key file.  The API key itself is
only ever placed inside the request Authorization/x-api-key header and is
never printed, logged, or included in exception messages.

Dialects: qwen/openai/deepseek/gemini/grok/muse/custom speak the OpenAI
chat-completions shape against per-provider base URLs; claude speaks the
native Anthropic messages shape (max_tokens REQUIRED, system as a top-level
field, x-api-key + anthropic-version headers, content = array of typed
blocks).

stdlib only (urllib), matching this directory's house style.
"""
from __future__ import annotations

import json
import os
import threading
from urllib.parse import urlsplit, urlunsplit
import urllib.error
import urllib.request

DEFAULT_CONFIG_PATH = "~/dev/uyp/state/ua-cloud.json"
# Test/ops override; companion-api always writes the default path.
CONFIG_ENV = "UYP_UA_CLOUD_CONFIG"

OPENAI_COMPAT_BASE_URLS = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    # These are the vendors' OpenAI-compatible *base* URLs.  Keep the path at
    # /v1; CloudClient appends /chat/completions.  The URLs are defaults only:
    # an operator can override ``base_url`` for an on-prem gateway or a
    # regional endpoint without changing code.
    "grok": "https://api.x.ai/v1",
    "muse": "https://api.meta.ai/v1",
}
CLAUDE_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_BASE_URL = "https://api.anthropic.com/v1"
CLAUDE_VERSION = "2023-06-01"
# ``custom`` is intentionally configuration-only: it is useful for a user's
# own OpenAI-compatible gateway, but the Studio catalog does not advertise it
# until HomeHub has a capability/allow-list entry for that endpoint.
PROVIDERS = tuple(OPENAI_COMPAT_BASE_URLS) + ("claude", "custom")

# Consecutive cloud failures that trip the per-job circuit breaker: the rest
# of the job degrades to structure-only and index_project marks its run-state
# (surfaced by ua_bridge as uaSummary["cloud_enrich_broken"] = true).
BREAKER_THRESHOLD = 5

DEFAULT_MAX_TOKENS = 2048
DEFAULT_TIMEOUT = 120.0


def _normalise_base_url(value: str) -> str:
    """Validate and canonicalise an operator-supplied API base URL.

    The config is written by the owner-facing HomeHub settings route, but it
    is still worth rejecting credentials, query strings, fragments, and
    unsupported schemes here.  ``http`` remains allowed for loopback/private
    gateways (for example a local OpenAI-compatible proxy); public endpoints
    should use HTTPS.
    """
    raw = str(value or "").strip()
    if not raw:
        raise CloudConfigError("UA cloud base_url must not be empty")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CloudConfigError("UA cloud base_url must be an http(s) URL")
    if parsed.username or parsed.password:
        raise CloudConfigError("UA cloud base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise CloudConfigError("UA cloud base_url must not contain a query or fragment")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        raise CloudConfigError(
            "UA cloud base_url must stop at the API base (do not include /chat/completions)")
    if not path:
        path = ""
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class CloudConfigError(RuntimeError):
    """Cloud mode requested but misconfigured (bad JSON, unknown provider,
    missing/empty key file).  Message names paths, never key material."""


class CloudError(RuntimeError):
    """One cloud call failed (HTTP status, transport, malformed/empty
    response).  Callers degrade the file honestly instead of crashing."""


def _http_post(url: str, payload: dict, headers: dict, timeout: float,
               *, redactions: tuple[str, ...] = ()) -> dict:
    """One JSON POST.  Raises CloudError on any failure; the API key lives
    only inside `headers` and is never copied into an exception message."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read()[:200].decode("utf-8", "replace")
        except Exception:
            detail = ""
        for secret in redactions:
            if secret:
                detail = detail.replace(secret, "[redacted]")
        raise CloudError(f"cloud provider HTTP {exc.code}: {detail}") from None
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        detail = str(exc)
        for secret in redactions:
            if secret:
                detail = detail.replace(secret, "[redacted]")
        raise CloudError(f"cloud provider call failed: {type(exc).__name__}: {detail}") from None


class CloudClient:
    """User-chosen cloud provider client.  One method matters to callers:

      chat(messages, *, max_tokens=None, timeout=None) -> (content, tokens)

    `messages` is the OpenAI shape ([{"role": ..., "content": str}]); the
    claude dialect split (system top-level, user/assistant only) happens
    internally.  Returns (text, total_tokens); tokens is 0 when the provider
    reported none.  Raises CloudError on any failure, including an empty
    completion (an empty enrichment must degrade honestly, not parse as "")."""

    def __init__(self, provider: str, model: str, api_key: str, *,
                 base_url: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 max_tokens: int = DEFAULT_MAX_TOKENS):
        self.provider = provider
        self.model = model
        self._api_key = api_key  # never printed; repr() below keeps it out
        default_url = (CLAUDE_BASE_URL if provider == "claude"
                       else OPENAI_COMPAT_BASE_URLS.get(provider))
        if default_url is None and not base_url:
            raise CloudConfigError(
                f"UA cloud provider {provider!r} needs an OpenAI-compatible base_url")
        self.base_url = _normalise_base_url(base_url or default_url)
        self.timeout = float(timeout)
        self.max_tokens = int(max_tokens)

    def __repr__(self):
        return f"CloudClient(provider={self.provider!r}, model={self.model!r})"

    # ---- request/response shapes (pure, unit-tested without network) ----
    def build_request(self, messages: list, max_tokens: int) -> tuple[str, dict, dict]:
        """(url, payload, headers) for one chat call in the provider dialect."""
        if self.provider == "claude":
            # Native Anthropic messages shape: max_tokens is REQUIRED, system
            # is a top-level field (never a message), content blocks come back
            # as a typed array.
            system = "\n\n".join(str(m.get("content", ""))
                                 for m in messages if m.get("role") == "system")
            turns = [{"role": m["role"], "content": m["content"]}
                     for m in messages if m.get("role") in ("user", "assistant")]
            payload = {"model": self.model, "max_tokens": int(max_tokens), "messages": turns}
            if system.strip():
                payload["system"] = system
            headers = {"x-api-key": self._api_key, "anthropic-version": CLAUDE_VERSION}
            return self.base_url.rstrip("/") + "/messages", payload, headers
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {"model": self.model, "messages": list(messages),
                   "max_tokens": int(max_tokens), "stream": False}
        # DashScope/Qwen's cloud switch uses this field rather than Ollama's
        # ``think`` flag.  Keep enrichment bounded and deterministic; other
        # OpenAI-compatible vendors simply receive the portable shape above.
        if self.provider == "qwen":
            payload["enable_thinking"] = False
        headers = {"Authorization": f"Bearer {self._api_key}"}
        return url, payload, headers

    def parse_response(self, data: dict) -> tuple[str, int]:
        """(content, total_tokens) out of the provider dialect's response."""
        if not isinstance(data, dict):
            raise CloudError("cloud provider returned a non-object JSON body")
        if self.provider == "claude":
            blocks = data.get("content")
            if not isinstance(blocks, list):
                raise CloudError("claude response without a content block array")
            content = "".join(str(b.get("text", "")) for b in blocks
                              if isinstance(b, dict) and b.get("type") == "text")
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        else:
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                raise CloudError("cloud response without choices")
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            raw_content = (message or {}).get("content") or ""
            if isinstance(raw_content, str):
                content = raw_content
            elif isinstance(raw_content, list):
                # Some OpenAI-compatible providers return multimodal/text
                # blocks even for a text-only prompt.  Keep only text blocks;
                # never stringify the list into Python repr noise.
                content = "".join(
                    str(block.get("text", ""))
                    for block in raw_content
                    if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
                )
            else:
                content = ""
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            tokens = int(usage.get("total_tokens") or
                         (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))
        if not content.strip():
            raise CloudError("cloud provider returned an empty completion")
        return content, tokens

    def chat(self, messages: list, *, max_tokens: int | None = None,
             timeout: float | None = None) -> tuple[str, int]:
        url, payload, headers = self.build_request(messages, max_tokens or self.max_tokens)
        data = _http_post(url, payload, headers, timeout or self.timeout,
                          redactions=(self._api_key,))
        try:
            return self.parse_response(data)
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise CloudError(f"malformed {self.provider} response: {type(exc).__name__}") from None


class CloudBreaker:
    """Per-job consecutive-failure circuit breaker (2026-10-15 contract).

    One cloud failure degrades THAT file to structure-only with a warning;
    BREAKER_THRESHOLD consecutive failures trip the breaker and the job's
    remaining files all degrade to structure-only.  Thread-safe: the index
    worker enriches over a ThreadPoolExecutor, so "consecutive" is counted
    under a lock rather than by wall-clock order."""

    def __init__(self, threshold: int = BREAKER_THRESHOLD):
        self.threshold = int(threshold)
        self.failures = 0
        self.tripped = False
        self._lock = threading.Lock()

    def ok(self) -> None:
        with self._lock:
            self.failures = 0

    def fail(self) -> bool:
        """Record one failure; True exactly once, on the failure that trips."""
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold and not self.tripped:
                self.tripped = True
                return True
            return False


def load_client(config_path: str | None = None) -> CloudClient | None:
    """Read the UA mode config and build the enrichment client.

    None -> local mode (config missing, or mode != "cloud"): callers keep the
    byte-identical local ollama path.  CloudConfigError -> cloud mode was
    requested but is misconfigured; callers warn and fall back to local.
    """
    path = os.path.expanduser(config_path or os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG_PATH)
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise CloudConfigError(f"UA cloud config unreadable ({path}): {exc}") from None
    if not isinstance(cfg, dict):
        raise CloudConfigError(f"UA cloud config must be a JSON object ({path})")
    if cfg.get("mode", "local") != "cloud":
        return None
    provider = str(cfg.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        raise CloudConfigError(
            f"UA cloud config {path}: unknown provider {provider!r} "
            f"(expected one of: {', '.join(PROVIDERS)})")
    model = str(cfg.get("model") or "").strip()
    if not model:
        raise CloudConfigError(f"UA cloud config {path}: cloud mode requires a \"model\"")
    configured_base = cfg.get("base_url")
    if provider == "custom" and not configured_base:
        raise CloudConfigError(
            f"UA cloud config {path}: custom provider requires a \"base_url\"")
    try:
        base_url = _normalise_base_url(
            configured_base or OPENAI_COMPAT_BASE_URLS.get(provider) or CLAUDE_BASE_URL)
    except CloudConfigError as exc:
        raise CloudConfigError(f"UA cloud config {path}: {exc}") from None
    key_source = str(cfg.get("api_key_source") or "file").strip().lower()
    if key_source not in {"file", "homehub"}:
        raise CloudConfigError(
            f"UA cloud config {path}: api_key_source must be file or homehub")
    handoff = None
    key_file = os.path.expanduser(str(cfg.get("api_key_file") or f"~/.config/homehub/{provider}.key"))
    try:
        with open(key_file, encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError:
        raise CloudConfigError(
            f"UA cloud mode for {provider} needs a readable API key file at {key_file} "
            "(0600, key text only); save the key through HomeHub or set mode back to local") from None
    if not key:
        raise CloudConfigError(f"UA cloud API key file is empty: {key_file}")
    return CloudClient(provider, model, key, base_url=base_url)
