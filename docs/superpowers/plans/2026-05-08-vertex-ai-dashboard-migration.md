# Vertex AI Dashboard Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the dashboard analysis path from deprecated Gemini API-key calls to a provider-based Vertex AI architecture that preserves the Raspberry Pi workflow and always returns structured JSON.

**Architecture:** Introduce a small provider boundary under a new shared `ai/` package, keep the existing specialist and fusion response contracts intact, and move `edge/web_server.py` to a dashboard-first flow that always prepares local evidence before attempting cloud calls. Runtime mode, auth source, and degraded behavior stay explicit through provider metadata so the UI and logs can report `vertex_expert`, `vertex_degraded`, or `local_heuristic` deterministically.

**Tech Stack:** Python, pydantic, PyYAML, existing `fusion.specialists` / `fusion.c06` stack, Google Vertex AI SDK (`google-genai` with Vertex mode plus `google-auth`), pytest/unittest web API tests.

---

## File Structure

- Create: `ai/__init__.py`
- Create: `ai/providers/__init__.py`
- Create: `ai/providers/base.py`
- Create: `ai/providers/local.py`
- Create: `ai/providers/vertex.py`
- Create: `ai/runtime.py`
- Create: `tests/test_ai_runtime.py`
- Create: `tests/test_ai_providers.py`
- Modify: `config/settings.yaml`
- Modify: `config/retry_policy.yaml`
- Modify: `fusion/specialists.py`
- Modify: `edge/web_server.py`
- Modify: `vision/gemini_client.py`
- Modify: `edge/potentiostat_client.py`
- Modify: `edge/quick_fusion_analyze.py`
- Modify: `edge/quick_analyze_potentiostat.py`
- Modify: `vision/quick_analyze.py`
- Modify: `tests/test_c05_specialists.py`
- Modify: `tests/test_web_session_api.py`
- Modify: `docs/runbooks/rpi-end-to-end-wet-test.md`
- Modify: `requirements.in`
- Modify: `requirements.lock`

### Task 1: Freeze The Dashboard Contract Before Migration

**Files:**
- Create: `tests/test_ai_runtime.py`
- Modify: `tests/test_web_session_api.py`
- Modify: `tests/test_c05_specialists.py`

- [ ] **Step 1: Add a failing runtime metadata test for explicit modes**

```python
def test_analysis_runtime_meta_reports_explicit_mode():
    runtime = web_server._analysis_runtime_meta(
        {
            "runtime_mode": "local_heuristic",
            "provider": "local_heuristic",
            "auth_mode": "disabled",
            "cloud_enabled": False,
        }
    )
    assert runtime["mode"] == "local_heuristic"
    assert runtime["provider"] == "local_heuristic"
    assert runtime["cloud_enabled"] is False
    assert "auth_mode" in runtime
```

- [ ] **Step 2: Add a failing `/api/session/analyze` stability test for degraded cloud failure**

```python
def test_analyze_returns_structured_json_when_provider_degrades(running_server):
    host, port, monkeypatch = running_server

    class _FakeCoordinator:
        def describe_runtime(self):
            return {
                "runtime_mode": "vertex_degraded",
                "provider": "vertex",
                "auth_mode": "adc",
                "auth_source": "adc",
                "cloud_enabled": True,
                "degraded_reason": "quota_exceeded",
            }

        def analyze_session(self, **kwargs):
            return kwargs["local_result"]

    monkeypatch.setattr(web_server, "_get_ai_runtime", lambda: _FakeCoordinator())
    status, raw = _request_json("POST", host, port, "/api/session/analyze", body={"min_readings": 5})
    payload = json.loads(raw.decode())
    assert status == 200
    assert payload["ok"] is True
    assert payload["ai_runtime"]["mode"] == "vertex_degraded"
    assert set(payload.keys()) >= {"sensor", "vision", "fused", "report", "ai_runtime", "timing"}
```

- [ ] **Step 3: Add a failing specialist fallback test for provider exceptions**

```python
def test_specialist_returns_degraded_payload_when_provider_fails():
    client = ScriptedClient([RuntimeError("permission denied"), RuntimeError("permission denied")])
    svc = SpecialistService(PROJECT_ROOT, client, settings=_settings(max_attempts=2), sleep_fn=lambda _: None)
    result = svc.run_sensor(cycle_id="cyc-vertex-1", sensor_input={"rp_ohm": 20000.0, "current_ma": 0.4, "status_band": "WARNING"})
    assert result["degraded_mode"] is True
    assert result["schema_version"] == "c05-sensor-v1"
    assert "permission" in result["fallback_reason"]
```

- [ ] **Step 4: Run the targeted tests to capture the current gap**

Run: `pytest tests/test_web_session_api.py -k analyze tests/test_c05_specialists.py tests/test_ai_runtime.py -v`
Expected: FAIL because the runtime metadata and provider boundary do not exist yet.

### Task 2: Introduce Explicit AI Settings And Runtime Metadata

**Files:**
- Create: `ai/runtime.py`
- Modify: `config/settings.yaml`
- Modify: `config/retry_policy.yaml`
- Modify: `fusion/specialists.py`

- [ ] **Step 1: Add explicit AI config fields to `config/settings.yaml`**

```yaml
ai:
  provider: vertex
  auth_mode: auto
  project_id: ""
  location: us-central1
  primary_model_id: gemini-2.5-flash
  fallback_model_id: gemini-2.5-pro
  enable_cloud_vision: true
  enable_cloud_orchestrator: true
  browser_timeout_seconds: 25
  sensor_timeout_seconds: 8
  vision_timeout_seconds: 10
  final_report_timeout_seconds: 7
```

- [ ] **Step 2: Add retry and circuit-breaker settings to `config/retry_policy.yaml`**

```yaml
retry:
  ai_call:
    max_attempts: 2
    timeout_seconds: 8
    backoff_seconds: 1
  ai_circuit_breaker:
    failures: 3
    cooldown_seconds: 120
```

- [ ] **Step 3: Create a shared runtime settings model in `ai/runtime.py`**

```python
@dataclass(frozen=True)
class AIConfig:
    provider: str
    auth_mode: str
    project_id: str
    location: str
    primary_model_id: str
    fallback_model_id: str
    enable_cloud_vision: bool
    enable_cloud_orchestrator: bool
    browser_timeout_seconds: float
    sensor_timeout_seconds: float
    vision_timeout_seconds: float
    final_report_timeout_seconds: float
    circuit_breaker_failures: int
    circuit_breaker_cooldown_seconds: float
```

- [ ] **Step 4: Update `fusion.specialists.AISettings` to consume the explicit config**

```python
return AISettings(
    primary_model_id=config.primary_model_id,
    fallback_model_id=config.fallback_model_id,
    response_mode="json",
    max_attempts=retry.max_attempts,
    timeout_seconds=config.sensor_timeout_seconds,
    backoff_seconds=retry.backoff_seconds,
)
```

- [ ] **Step 5: Run config- and specialist-focused tests**

Run: `pytest tests/test_c05_specialists.py tests/test_ai_runtime.py -v`
Expected: PASS for config loading and existing specialist behavior, while web-path tests still fail.

### Task 3: Add The Provider Boundary With Local Fallback First

**Files:**
- Create: `ai/providers/base.py`
- Create: `ai/providers/local.py`
- Create: `tests/test_ai_providers.py`

- [ ] **Step 1: Create provider protocols and runtime metadata models**

```python
class AIProvider(Protocol):
    def generate_structured_text(self, *, prompt: str, model_id: str, timeout_seconds: float) -> str: ...
    def analyze_image_with_context(self, *, image_path: str | Path, prompt: str, model_id: str, timeout_seconds: float) -> str: ...
    def health_check(self) -> dict[str, Any]: ...
    def describe_runtime(self) -> dict[str, Any]: ...
```

- [ ] **Step 2: Add `LocalHeuristicProvider` that never raises on cloud absence**

```python
class LocalHeuristicProvider:
    def describe_runtime(self) -> dict[str, Any]:
        return {
            "provider": "local_heuristic",
            "runtime_mode": "local_heuristic",
            "auth_mode": self.config.auth_mode,
            "auth_source": "disabled" if self.config.auth_mode == "disabled" else "none",
            "cloud_enabled": False,
        }
```

- [ ] **Step 3: Add provider tests for disabled/no-credential behavior**

```python
def test_local_provider_reports_local_heuristic_mode():
    provider = LocalHeuristicProvider(config=_config(auth_mode="disabled"))
    runtime = provider.describe_runtime()
    assert runtime["runtime_mode"] == "local_heuristic"
    assert runtime["cloud_enabled"] is False
```

- [ ] **Step 4: Run the provider tests**

Run: `pytest tests/test_ai_providers.py tests/test_ai_runtime.py -v`
Expected: PASS for local fallback provider coverage.

### Task 4: Implement Vertex Provider Auth Resolution, Timeouts, And Circuit Breaker

**Files:**
- Create: `ai/providers/vertex.py`
- Modify: `requirements.in`
- Modify: `requirements.lock`
- Modify: `tests/test_ai_providers.py`

- [ ] **Step 1: Replace deprecated dependency declarations**

```text
pyyaml
python-json-logger
pydantic
Pillow
google-genai
google-auth
pyserial
```

- [ ] **Step 2: Implement auth resolution with `auto|adc|service_account|disabled`**

```python
def resolve_auth(self) -> ResolvedAuth:
    if self.config.auth_mode == "disabled":
        return ResolvedAuth(source="disabled", cloud_enabled=False, project_id=self.config.project_id)
    if self.config.auth_mode in {"auto", "service_account"} and os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        return ResolvedAuth(source="service_account", cloud_enabled=True, project_id=self._project_from_credentials())
    if self.config.auth_mode in {"auto", "adc"}:
        credentials, project_id = google.auth.default()
        return ResolvedAuth(source="adc", cloud_enabled=True, project_id=project_id or self.config.project_id)
    return ResolvedAuth(source="none", cloud_enabled=False, project_id=self.config.project_id)
```

- [ ] **Step 3: Add bounded call execution and classified failures**

```python
def generate_structured_text(self, *, prompt: str, model_id: str, timeout_seconds: float) -> str:
    self._ensure_call_allowed()
    try:
        return self._run_with_timeout(lambda: self._text_client(model_id).generate_content(prompt), timeout_seconds)
    except Exception as exc:
        classified = self._classify_error(exc)
        self._record_failure(classified)
        raise
```

- [ ] **Step 4: Add circuit-breaker tests for repeated failures and cooldown**

```python
def test_vertex_provider_trips_breaker_after_repeated_failures():
    provider = VertexAIProvider(config=_config(), clock=FakeClock())
    provider._record_failure("quota_exceeded")
    provider._record_failure("quota_exceeded")
    provider._record_failure("quota_exceeded")
    runtime = provider.describe_runtime()
    assert runtime["runtime_mode"] == "local_heuristic"
    assert runtime["circuit_breaker_open"] is True
```

- [ ] **Step 5: Run provider tests**

Run: `pytest tests/test_ai_providers.py -v`
Expected: PASS for ADC, service-account, no-credential, timeout, malformed output, and breaker coverage.

### Task 5: Refactor Specialists To Depend On The Provider Interface

**Files:**
- Modify: `fusion/specialists.py`
- Modify: `tests/test_c05_specialists.py`

- [ ] **Step 1: Rename the protocol to provider-neutral text generation**

```python
class StructuredTextGenerator(Protocol):
    def generate_structured_text(self, *, prompt: str, model_id: str, timeout_seconds: float) -> str:
        """Return a JSON string from the configured provider."""
```

- [ ] **Step 2: Update `SpecialistService` to call the new provider method**

```python
raw = self.client.generate_structured_text(
    model_id=model_id,
    prompt=prompt,
    timeout_seconds=timeout_seconds,
)
```

- [ ] **Step 3: Preserve stale fallback semantics and fallback-model retry behavior**

```python
except TimeoutError as exc:
    last_error = f"timeout:{exc}"
except Exception as exc:
    last_error = f"provider_exception:{type(exc).__name__}:{exc}"
```

- [ ] **Step 4: Expand specialist tests to cover cloud failure, stale fallback reuse, and final-orchestrator timeout**

```python
def test_final_interpretation_timeout_returns_degraded_payload():
    client = ScriptedClient([TimeoutError("final timeout"), TimeoutError("final timeout")])
    svc = SpecialistService(PROJECT_ROOT, client, settings=_settings(max_attempts=2), sleep_fn=lambda _: None)
    result = svc.run_final_interpretation(cycle_id="cyc-final-1", orchestrator_input={"fused": {"confidence_0_to_1": 0.4}})
    assert result["degraded_mode"] is True
    assert result["schema_version"] == "c05-final-v1"
```

- [ ] **Step 5: Run specialist tests**

Run: `pytest tests/test_c05_specialists.py -v`
Expected: PASS with provider-neutral specialists and unchanged response schemas.

### Task 6: Migrate `/api/session/analyze` To The Dashboard-First Provider Flow

**Files:**
- Modify: `edge/web_server.py`
- Modify: `tests/test_web_session_api.py`

- [ ] **Step 1: Add a shared AI runtime/coordinator entrypoint in `edge/web_server.py`**

```python
def _get_ai_runtime():
    global _ai_runtime
    if _ai_runtime is None:
        with _svc_lock:
            if _ai_runtime is None:
                _ai_runtime = build_ai_runtime(PROJECT_ROOT)
    return _ai_runtime
```

- [ ] **Step 2: Build local evidence before any cloud call**

```python
local_sensor = _build_sensor_payload(readings, cycle_id)
local_vision = _build_vision_payload(raw_vision, cycle_id) if raw_vision else _no_vision_payload(cycle_id)
local_fused = fs.fuse(cycle_id=cycle_id, sensor_payload=local_sensor, vision_payload=local_vision)
local_result = {"sensor": local_sensor, "vision": local_vision, "fused": local_fused}
```

- [ ] **Step 3: Attempt cloud specialists only when runtime allows it**

```python
runtime = _get_ai_runtime()
ai_runtime = runtime.describe_runtime()
if ai_runtime["runtime_mode"] == "vertex_expert":
    sensor_payload = specialist_service.run_sensor(...)
    vision_payload = specialist_service.run_vision(...)
else:
    sensor_payload = local_sensor
    vision_payload = local_vision
```

- [ ] **Step 4: Degrade per stage instead of failing the request**

```python
try:
    ai_report = specialist_service.run_final_interpretation(...)
except Exception:
    ai_report = None

report = _build_analysis_report(...)
if ai_report is not None:
    report = _merge_ai_report(report, ai_report)
```

- [ ] **Step 5: Update analyze tests for `vertex_expert`, `vertex_degraded`, and `local_heuristic`**

```python
assert payload["ai_runtime"]["mode"] == "vertex_degraded"
assert payload["report"]["ai_detailed_report"]["degraded_mode"] is True
assert payload["sensor"]["schema_version"] == "c05-sensor-v1"
assert payload["vision"]["schema_version"] == "c05-vision-v1"
```

- [ ] **Step 6: Run the analyze-path tests**

Run: `pytest tests/test_web_session_api.py -k analyze -v`
Expected: PASS with stable top-level JSON on success, auth failure, quota failure, timeout, and malformed provider output.

### Task 7: Surface Runtime Mode, Auth Source, And Degraded Status In Reports And UI

**Files:**
- Modify: `edge/web_server.py`
- Modify: `docs/runbooks/rpi-end-to-end-wet-test.md`

- [ ] **Step 1: Expand `ai_runtime` metadata returned to the frontend**

```python
return {
    "mode": runtime["runtime_mode"],
    "provider": runtime["provider"],
    "auth_mode": runtime["auth_mode"],
    "auth_source": runtime["auth_source"],
    "project_id": runtime["project_id"],
    "location": runtime["location"],
    "cloud_enabled": runtime["cloud_enabled"],
    "degraded_reason": runtime.get("degraded_reason", ""),
    "circuit_breaker_open": runtime.get("circuit_breaker_open", False),
}
```

- [ ] **Step 2: Make deterministic report text mention `vertex_expert`, `vertex_degraded`, or `local_heuristic`**

```python
if ai_mode == "vertex_degraded":
    quality_points.append("Cloud expert analysis partially degraded; deterministic fallbacks were used for at least one stage.")
elif ai_mode == "local_heuristic":
    quality_points.append("Cloud analysis was unavailable, so the report was produced entirely from the local heuristic pipeline.")
```

- [ ] **Step 3: Update the wet-test runbook with ADC, service-account, and forced-local checks**

```markdown
CORR__AI__AUTH_MODE=disabled python edge/web_server.py
CORR__AI__AUTH_MODE=adc python edge/web_server.py
CORR__AI__AUTH_MODE=service_account GOOGLE_APPLICATION_CREDENTIALS=/path/key.json python edge/web_server.py
```

- [ ] **Step 4: Run targeted analyze tests again after UI/report metadata changes**

Run: `pytest tests/test_web_session_api.py -k analyze -v`
Expected: PASS with mode-specific runtime metadata and unchanged top-level response shape.

### Task 8: Migrate Helper Clients And Scripts Without Breaking Local Lab Usage

**Files:**
- Modify: `vision/gemini_client.py`
- Modify: `edge/potentiostat_client.py`
- Modify: `vision/quick_analyze.py`
- Modify: `edge/quick_analyze_potentiostat.py`
- Modify: `edge/quick_fusion_analyze.py`

- [ ] **Step 1: Rework helper clients into Vertex-backed compatibility wrappers**

```python
class VisionAIClient:
    def __init__(self, provider: AIProvider | None = None):
        self.provider = provider or build_ai_runtime(PROJECT_ROOT).provider

    def analyze_image_file(self, image_path, context=None):
        prompt = self._build_prompt(context)
        return json.loads(
            self.provider.analyze_image_with_context(
                image_path=image_path,
                prompt=prompt,
                model_id=self.model_id,
                timeout_seconds=self.timeout_seconds,
            )
        )
```

- [ ] **Step 2: Keep local fallback behavior explicit in script output**

```python
if runtime["runtime_mode"] != "vertex_expert":
    print(f"AI runtime: {runtime['runtime_mode']} ({runtime.get('degraded_reason', 'local fallback')})")
```

- [ ] **Step 3: Run helper script smoke tests in dry mode**

Run: `pytest tests/test_ai_providers.py tests/test_c05_specialists.py tests/test_web_session_api.py -k "analyze or provider" -v`
Expected: PASS before removing deprecated imports.

### Task 9: Remove Deprecated `google.generativeai` Usage After Parity Is Proven

**Files:**
- Modify: `edge/web_server.py`
- Modify: `vision/gemini_client.py`
- Modify: `edge/potentiostat_client.py`
- Modify: `requirements.in`
- Modify: `requirements.lock`

- [ ] **Step 1: Delete direct `google.generativeai` adapter code from `edge/web_server.py`**

```python
# Remove:
class _GeminiModelClient: ...
def _get_specialist_service(): ...
def _get_gemini_vision_client(): ...
```

- [ ] **Step 2: Remove deprecated package references once all tests are green**

Run: `rg -n "google\\.generativeai|GenerativeModel|GOOGLE_API_KEY" edge vision tests requirements.*`
Expected: no remaining dashboard-path dependency on deprecated Gemini API-key calls.

- [ ] **Step 3: Run the full relevant test suite**

Run: `pytest tests/test_ai_runtime.py tests/test_ai_providers.py tests/test_c05_specialists.py tests/test_c06_fusion.py tests/test_c07_orchestration.py tests/test_web_session_api.py -v`
Expected: PASS.

### Task 10: Final Pi-Safe Verification Before Completion

**Files:**
- Modify: none

- [ ] **Step 1: Verify runtime mode selection explicitly**

Run: `CORR__AI__AUTH_MODE=disabled pytest tests/test_web_session_api.py -k analyze -v`
Expected: PASS with `local_heuristic` mode.

- [ ] **Step 2: Verify degraded-mode stability**

Run: `pytest tests/test_web_session_api.py tests/test_ai_providers.py -k "degraded or breaker or analyze" -v`
Expected: PASS with no empty reply and no uncaught request crash.

- [ ] **Step 3: Verify no deprecated call sites remain in the dashboard path**

Run: `rg -n "google\\.generativeai|gemini_specialists" edge vision fusion tests`
Expected: only intentionally renamed compatibility references, or no matches after cleanup.

- [ ] **Step 4: Commit the migration in small safe checkpoints**

```bash
git add ai config tests fusion edge vision docs requirements.in requirements.lock
git commit -m "feat: add provider-based Vertex AI runtime"
git commit -m "feat: migrate dashboard analysis to provider runtime"
git commit -m "chore: remove deprecated generativeai path"
```

## Self-Review

- Spec coverage: covered provider abstraction, Vertex auth modes, runtime modes, local-first request prep, layered degradation, circuit breaker, UI/runtime observability, dashboard-first rollout, helper migration, and deprecated path removal.
- Placeholder scan: no `TODO`, `TBD`, or “handle later” markers remain.
- Type consistency: the plan consistently uses `generate_structured_text`, `analyze_image_with_context`, `describe_runtime`, and runtime modes `vertex_expert`, `vertex_degraded`, `local_heuristic`.
