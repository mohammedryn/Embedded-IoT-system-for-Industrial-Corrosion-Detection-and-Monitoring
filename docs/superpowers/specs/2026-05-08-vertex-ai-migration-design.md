# Vertex AI Migration Design

Date: 2026-05-08
Status: Proposed
Scope: Dashboard-first migration of cloud AI analysis from deprecated Gemini API-key usage to a provider-based Vertex AI architecture with safe fallback behavior.

## 1. Goal

Migrate the corrosion analysis system from direct `google.generativeai` API-key calls to a stable, billed, and observable Google Cloud Vertex AI path without breaking the existing Raspberry Pi lab workflow.

The migrated system must preserve the intended product behavior:

- electrochemical specialist interpretation based on Rp/LPR data
- Gemini-backed image interpretation of the captured steel surface
- final orchestrated corrosion interpretation that fuses sensor and vision evidence
- continued operation when cloud AI is unavailable

The migration must also preserve the current demo-critical behavior:

- the Pi web app still starts normally
- `/api/session/analyze` always returns a structured response
- the app never hangs indefinitely at analysis time
- the operator can still finish a lab session without cloud access

## 2. Non-Goals

This design does not include:

- redesigning the potentiostat math or firmware
- replacing the local HSV/pitting-proxy pipeline
- rewriting the fusion scoring model
- introducing a multi-provider marketplace beyond Vertex and local fallback in this phase
- implementing headless production secret rotation infrastructure

Those can be addressed later if needed.

## 3. Current State Summary

The current codebase uses deprecated `google.generativeai` calls in several places:

- `edge/web_server.py` for the live lab-session flow
- `vision/gemini_client.py` for image analysis
- `edge/potentiostat_client.py`
- helper scripts under `vision/` and `edge/`

Current pain points:

- free-tier Gemini API quotas are easy to exhaust
- rate-limit and quota failures can degrade the user experience
- the provider logic is spread across multiple files
- the dashboard analysis path mixes orchestration concerns with provider concerns
- the current cloud path is not aligned with the user’s Google Cloud credits and preferred billing model

Recent work has already improved:

- local heuristic fallback behavior
- richer research-backed corrosion memory
- a more detailed report structure
- bounded final report generation timing

This migration should build on those improvements rather than replace them.

## 4. Design Principles

The migration will follow these principles:

1. Cloud AI is preferred, not required.
2. The web workflow must not crash because a provider failed.
3. Provider-specific logic must not leak into the session orchestration layer.
4. Authentication and runtime mode must be explicit and observable.
5. The migration must be incremental and reversible.
6. The system must support both interactive lab Pi usage and future semi-headless deployment.

## 5. Recommended Architecture

### 5.1 High-Level Structure

Introduce a new internal AI provider boundary between the application logic and the cloud SDK.

Proposed layers:

- `AI Provider Layer`
- `Specialist Layer`
- `Fusion Layer`
- `Web Session Orchestration Layer`

The provider layer owns:

- auth resolution
- model selection
- SDK calls
- retries and backoff
- timeout handling
- quota/auth/network error classification

The specialist layer owns:

- prompt construction
- schema validation
- corrosion memory injection
- degraded structured fallback payloads

The fusion layer owns:

- severity combination
- confidence synthesis
- RUL estimation

The web layer owns:

- session lifecycle
- readings/photo collection
- invoking the specialists
- returning a complete JSON response to the UI

### 5.2 Provider Interface

Add a small internal provider interface that is independent of any Google SDK details.

Minimum responsibilities:

- `generate_structured_text(prompt, model_id, timeout_seconds)`
- `analyze_image_with_context(image_path, prompt, model_id, timeout_seconds)`
- `health_check()`
- `describe_runtime()`

`describe_runtime()` should expose enough information for logs and UI:

- provider name
- auth source
- effective project
- location
- model IDs
- degraded/circuit-breaker state

### 5.3 Provider Implementations

Phase-1 implementations:

- `VertexAIProvider`
- `LocalHeuristicProvider`

`VertexAIProvider` is the target production provider.

`LocalHeuristicProvider` is not a general LLM substitute. It exists to preserve structured report completion when cloud AI is unavailable.

### 5.4 Specialist Ownership

The current specialist model is kept because it matches the product well:

- electrochemical specialist
- vision specialist
- final orchestrator specialist

These specialists must stop knowing about Google auth or SDK details. They should only depend on the provider interface.

## 6. Authentication Design

### 6.1 Supported Auth Modes

The system will support:

- `adc`
- `service_account`
- `auto`
- `disabled`

### 6.2 Resolution Order

When `auth_mode=auto`, resolve credentials in this order:

1. explicit service-account JSON via `GOOGLE_APPLICATION_CREDENTIALS`
2. Application Default Credentials
3. no cloud credentials available

If no cloud credentials are available, the system must start successfully and enter `local_heuristic` mode.

### 6.3 Pi Deployment Targets

The design must support both:

- interactive lab Pi operation
- future headless or semi-headless deployment

Operational preference:

- use ADC when the Pi is operated interactively and can be authenticated with Google Cloud tooling
- use a service-account file when the Pi must be more appliance-like or deterministic

### 6.4 Auth Observability

At startup and in runtime metadata, expose:

- auth mode configured
- auth source resolved
- effective provider
- project ID
- location
- whether cloud AI is enabled

## 7. Runtime Modes

The system will formalize three runtime modes:

### 7.1 `vertex_expert`

Cloud auth is valid, Vertex is reachable, and specialist/orchestrator calls are enabled.

This is the intended rich-analysis mode.

### 7.2 `vertex_degraded`

Cloud mode is configured, but one or more cloud calls fail due to:

- timeout
- quota exhaustion
- permission error
- transient network failure
- malformed or invalid model output

The request must still return a complete result using structured degraded specialist outputs and deterministic report fallbacks as needed.

### 7.3 `local_heuristic`

No usable cloud credentials are available, cloud mode is disabled, or a temporary provider circuit breaker is active.

In this mode:

- sensor interpretation is local
- image interpretation is local
- fusion remains local
- the final report is deterministic and clearly labeled as local

## 8. Request Flow

### 8.1 Preparation Stage

For every `/api/session/analyze` request, always prepare local evidence first:

- sensor summary from readings
- local image analysis from best photo
- local fused numeric result

This guarantees the app always has a complete fallback path before attempting cloud work.

### 8.2 Cloud Specialist Stage

When the runtime mode allows cloud use:

- electrochemical specialist receives structured sensor evidence plus corrosion memory
- vision specialist receives the selected real image plus local visual summary plus corrosion memory
- final orchestrator receives sensor specialist output, vision specialist output, fused payload, and runtime context

### 8.3 Timeout Budgeting

Each cloud stage gets its own timeout budget.

Minimum independent budgets:

- sensor specialist timeout
- vision specialist timeout
- final orchestrator timeout

The final orchestrator timeout must be lower than the browser’s overall wait threshold so the server can still respond cleanly.

### 8.4 Layered Degradation

Failure of one stage must not kill the entire analysis.

Rules:

- if the sensor specialist fails, use local electrochemical interpretation seed
- if the vision specialist fails, use local vision interpretation seed
- if the final orchestrator fails, return the fused result with deterministic report sections
- if the provider itself is unavailable, return a complete local result immediately

### 8.5 Unified Response Shape

The frontend always receives the same top-level structure:

- `sensor`
- `vision`
- `fused`
- `report`
- `ai_runtime`
- `timing`

Only the runtime metadata and detail richness change by mode.

## 9. Circuit Breaker And Failure Policy

To avoid quota storms and bad UX, add a temporary provider circuit breaker.

### 9.1 Trigger Conditions

Trip the breaker after repeated cloud failures such as:

- repeated quota errors
- repeated permission/auth failures
- repeated connection failures
- repeated model response validation failures

### 9.2 Breaker Behavior

During the cooldown window:

- do not attempt full cloud analysis
- serve local or degraded mode directly
- expose cooldown status in runtime metadata

### 9.3 Recovery

After the cooldown period, the provider may attempt cloud calls again.

This keeps the system from hammering Vertex and makes operator behavior predictable.

## 10. UI And Operator Experience

The operator must always know what kind of analysis they received.

The UI should clearly show:

- current runtime mode
- whether the report used cloud expert interpretation
- whether image review used raw-image cloud analysis or local morphology only
- whether the report was degraded and why

The report itself should stay useful in every mode:

- `vertex_expert`: rich cloud-backed report
- `vertex_degraded`: partially cloud-backed but explicitly degraded
- `local_heuristic`: deterministic fallback report

## 11. Configuration Model

Replace the vague current AI config with explicit settings.

Recommended config fields:

- `ai.provider`
- `ai.auth_mode`
- `ai.project_id`
- `ai.location`
- `ai.primary_model_id`
- `ai.fallback_model_id`
- `ai.enable_cloud_vision`
- `ai.enable_cloud_orchestrator`
- `ai.circuit_breaker_failures`
- `ai.circuit_breaker_cooldown_seconds`
- `ai.browser_timeout_seconds`
- `ai.sensor_timeout_seconds`
- `ai.vision_timeout_seconds`
- `ai.final_report_timeout_seconds`

Recommended values:

- `provider = vertex`
- `auth_mode = auto`
- `enable_cloud_vision = true`
- `enable_cloud_orchestrator = true`

## 12. Testing Strategy

### 12.1 Provider Tests

Test:

- ADC available
- service-account file available
- no credentials
- quota failure
- permission failure
- timeout
- malformed model output

### 12.2 Specialist Tests

Test:

- cloud success
- cloud failure with degraded fallback
- stale fallback reuse
- final orchestrator timeout with successful fused response

### 12.3 Web Flow Tests

Test:

- `/api/session/analyze` always returns valid JSON
- no empty server reply on cloud failure
- no uncaught request crash
- runtime mode metadata matches behavior

### 12.4 Pi Operational Checks

Test:

- ADC detection
- service-account detection
- startup mode messaging
- one complete run in `vertex_expert`
- one complete run in forced local mode

## 13. Rollout Plan

### Phase 1: Provider Abstraction

Introduce the provider interface and wrap the existing cloud logic behind it without changing user-facing behavior.

### Phase 2: Vertex Provider

Implement `VertexAIProvider` with:

- ADC support
- service-account fallback
- runtime metadata
- quota/error classification

Keep it disabled by default until validated.

### Phase 3: Dashboard-First Migration

Move the main web session analysis path to the new provider path first.

This is the most important path for demo reliability.

### Phase 4: Circuit Breaker And Degraded Reporting

Add cooldown behavior and richer runtime-mode reporting.

### Phase 5: Helper Script Migration

Migrate:

- quick analysis scripts
- helper AI clients
- other direct Gemini call sites

### Phase 6: Deprecated Path Removal

Once parity is proven, remove the deprecated `google.generativeai` path from the repo.

## 14. Success Criteria

The migration is successful when:

- Vertex-backed analysis can use the user’s Google Cloud project and billing
- the Pi app can run in `vertex_expert`, `vertex_degraded`, and `local_heuristic` modes
- `/api/session/analyze` never crashes because of provider failure
- the UI accurately reports which mode generated the output
- the cloud-backed path produces the intended rich corrosion interpretation when available
- local heuristic fallback remains available and reliable

## 15. Risks And Mitigations

### Risk: Cloud migration breaks the demo

Mitigation:

- dashboard-first rollout
- keep local heuristic intact
- preserve current response shape

### Risk: Vertex auth becomes harder for Pi operators

Mitigation:

- support both ADC and service-account auth
- make auth resolution explicit and visible

### Risk: Cloud quotas or timeouts still degrade UX

Mitigation:

- independent timeouts
- circuit breaker
- deterministic degraded response path

### Risk: Provider abstraction adds too much complexity

Mitigation:

- keep the interface small
- support only Vertex and local fallback in this migration

## 16. Recommendation

Proceed with a phased migration built around a provider abstraction, with Vertex AI as the primary provider and local heuristic as the guaranteed fallback.

This is the cleanest way to:

- use Google Cloud billing and credits properly
- preserve the intended Gemini-quality corrosion interpretation
- keep the Raspberry Pi demo stable
- avoid breaking the system during migration
