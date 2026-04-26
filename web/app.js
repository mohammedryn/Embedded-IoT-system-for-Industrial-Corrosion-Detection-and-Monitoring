function updateDashboard(state) {
    // Basic info
    document.getElementById('cycle_id').textContent = state.cycle_id || '--';
    document.getElementById('timestamp').textContent = state.timestamp ? new Date(state.timestamp).toLocaleTimeString() : '--';

    // Phases Timeline
    const phasesContainer = document.getElementById('phases_container');
    const phaseMarkers = state.phase_markers || ['baseline', 'acceleration', 'active', 'severe', 'fresh_swap'];
    phasesContainer.innerHTML = ''; // basic clear
    phaseMarkers.forEach(marker => {
        const div = document.createElement('div');
        div.className = 'phase-pill' + (marker === state.phase ? ' active' : '');
        div.textContent = marker.replace('_', ' ');
        phasesContainer.appendChild(div);
    });

    // Electrochemical
    if (state.rp_ohm !== undefined) animateValue('rp_ohm', parseFloat(document.getElementById('rp_ohm').textContent.replace(/,/g, '')), state.rp_ohm, 800, true);
    if (state.current_ma !== undefined) document.getElementById('current_ma').textContent = state.current_ma.toFixed(3);
    
    // BADGES - SENSOR
    const sensorBadge = document.getElementById('sensor_status');
    const sBand = (state.sensor_status_band || 'UNKNOWN').toUpperCase();
    sensorBadge.textContent = sBand;
    sensorBadge.className = 'badge status-' + sBand.toLowerCase();

    // Vision
    if (state.vision_severity_0_to_10 !== undefined) document.getElementById('vision_severity').textContent = state.vision_severity_0_to_10.toFixed(2);
    
    // BADGES - VISION Quality
    const vBadge = document.getElementById('vision_quality');
    let vQual = "FRESH";
    if (state.degraded_mode && state.stale) vQual = "DEGRADED_STALE";
    else if (state.degraded_mode) vQual = "DEGRADED";
    else if (state.stale) vQual = "STALE";
    vBadge.textContent = vQual.replace('_', ' ');
    vBadge.className = `badge status-${vQual.split('_')[0].toLowerCase()}`;

    const flags = state.vision_quality_flags || [];
    document.getElementById('vision_flags').textContent = flags.length ? flags.join(', ') : 'None';

    // Confidence
    const confRaw = state.confidence_0_to_1 !== undefined ? state.confidence_0_to_1 : 0;
    const confPct = Math.round(confRaw * 100);
    animateValue('confidence_percent', parseInt(document.getElementById('confidence_percent').textContent), confPct, 800, false);
    document.getElementById('confidence_bar').style.width = `${confPct}%`;

    const pulse = document.getElementById('confidence_pulse');
    if (confPct >= 80) pulse.style.background = 'var(--ok-text)';
    else if (confPct >= 50) pulse.style.background = 'var(--warn-text)';
    else pulse.style.background = 'var(--crit-text)';

    // RUL & Fused Severity
    if (state.rul_days !== undefined) animateValue('rul_days', parseFloat(document.getElementById('rul_days').textContent), state.rul_days, 1000, false);
    if (state.fused_severity_0_to_10 !== undefined) document.getElementById('fused_severity').textContent = state.fused_severity_0_to_10.toFixed(2);

    // Apply Glows Based on Fused Severity Warning Bands
    const rulCard = document.getElementById('card_rul');
    rulCard.className = 'card stat-card highlight';
    if (state.fused_severity_0_to_10 >= 7.5) {
        rulCard.classList.add('glow-critical');
    } else if (state.fused_severity_0_to_10 >= 4.0) {
        rulCard.classList.add('glow-warning');
    }

    // Toggle button states based on pause
    const btnPause = document.getElementById('btn_pause');
    const btnResume = document.getElementById('btn_resume');
    if (state.paused) {
        btnPause.style.display = 'none';
        btnResume.style.display = 'inline-block';
    } else {
        btnPause.style.display = 'inline-block';
        btnResume.style.display = 'none';
    }
}

// Quick number animation
function animateValue(id, start, end, duration, formatCommas) {
    if (start === end || isNaN(start)) {
        if(formatCommas && !isNaN(end)) {
            document.getElementById(id).textContent = Math.round(end).toLocaleString('en-US');
        } else {
            document.getElementById(id).textContent = end;
        }
        return;
    }
    const range = end - start;
    let current = start;
    const increment = end > start ? 1 : -1;
    const stepTime = Math.abs(Math.floor(duration / Math.max(1, range)));
    const finalStep = stepTime < 10 ? 10 : stepTime;
    
    // Instead of precise intervals, do a smooth curve for premium feel
    const startTimeElement = performance.now();
    
    function update(time) {
        const elapsed = time - startTimeElement;
        const progress = Math.min(elapsed / duration, 1);
        
        // easeOutQuart
        const ease = 1 - Math.pow(1 - progress, 4);
        const currentVal = start + (range * ease);
        
        if (id === 'rul_days') {
            document.getElementById(id).textContent = currentVal.toFixed(1);
        } else if (formatCommas) {
            document.getElementById(id).textContent = Math.round(currentVal).toLocaleString('en-US');
        } else {
            document.getElementById(id).textContent = Math.round(currentVal);
        }

        if (progress < 1) {
            requestAnimationFrame(update);
        } else {
            if (id === 'rul_days') document.getElementById(id).textContent = end.toFixed(1);
            else if (formatCommas) document.getElementById(id).textContent = Math.round(end).toLocaleString('en-US');
            else document.getElementById(id).textContent = Math.round(end);
        }
    }
    requestAnimationFrame(update);
}


async function pollState() {
    try {
        const res = await fetch('/api/state');
        if (res.ok) {
            const data = await res.json();
            updateDashboard(data);
        }
    } catch (e) {
        console.warn("Polling error:", e);
    }
    setTimeout(pollState, 2000);
}

async function sendControl(action) {
    try {
        await fetch('/api/control', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ action })
        });
        // Optimistic poll
        pollState();
    } catch (e) {
        console.error("Control error:", e);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn_pause').onclick = () => sendControl('pause');
    document.getElementById('btn_resume').onclick = () => sendControl('resume');
    document.getElementById('btn_recapture').onclick = () => sendControl('recapture');
    document.getElementById('btn_recompute').onclick = () => sendControl('recompute');

    pollState();
    initTabs();
    LabSession.init();
});

// ═══════════════════════════════════════
// TAB SWITCHING
// ═══════════════════════════════════════
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.dataset.tab;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
            btn.classList.add('active');
            document.getElementById('tab-' + target).classList.remove('hidden');
        });
    });
}

// ═══════════════════════════════════════
// LAB SESSION CONTROLLER
// ═══════════════════════════════════════
const LabSession = (() => {
    let currentStep = 1;
    let photos = [];        // [{id, path, captured_at, thumbnail_b64}]
    let readings = [];      // raw frames from SSE
    let sseSource = null;
    let collecting = false;
    let serialConnected = false;
    let analyzeRunning = false;
    let previewTimer = null;
    let previewBusy = false;
    let previewObjectUrl = null;

    function init() {
        // Step navigation
        document.getElementById('btn-step1-next').addEventListener('click', () => goToStep(2));
        document.getElementById('btn-step2-back').addEventListener('click', () => goToStep(1));
        document.getElementById('btn-step2-next').addEventListener('click', () => goToStep(3));
        document.getElementById('btn-step3-back').addEventListener('click', () => goToStep(2));

        // Step 1
        document.getElementById('btn-refresh-preview').addEventListener('click', () => refreshCameraPreview(true));
        document.getElementById('btn-capture').addEventListener('click', capturePhoto);
        document.getElementById('btn-clear-photos').addEventListener('click', clearPhotos);

        // Step 2
        document.getElementById('btn-serial-connect').addEventListener('click', connectSerial);
        document.getElementById('btn-serial-disconnect').addEventListener('click', disconnectSerial);
        document.getElementById('btn-start-collecting').addEventListener('click', startCollecting);
        document.getElementById('btn-stop-collecting').addEventListener('click', stopCollecting);

        // Step 3
        document.getElementById('btn-analyze').addEventListener('click', runAnalysis);
        document.getElementById('btn-new-session').addEventListener('click', newSession);

        // Initialize new server-side session
        fetch('/api/session/new', { method: 'POST' }).catch(() => {});
        startCameraPreviewLoop();
    }

    // ─── STEP NAVIGATION ────────────────────────────────────────────
    function goToStep(n) {
        document.getElementById('step-panel-' + currentStep).classList.add('hidden');
        document.getElementById('step-panel-' + n).classList.remove('hidden');

        // Update stepper indicators
        for (let i = 1; i <= 3; i++) {
            const circle = document.getElementById('stepper-' + i);
            circle.classList.remove('active', 'done');
            if (i < n) circle.classList.add('done');
            else if (i === n) circle.classList.add('active');
        }
        // Update connectors
        document.getElementById('connector-1-2').classList.toggle('done', n > 1);
        document.getElementById('connector-2-3').classList.toggle('done', n > 2);

        currentStep = n;

        if (n === 1) startCameraPreviewLoop();
        else stopCameraPreviewLoop();

        if (n === 2) refreshStep2();
        if (n === 3) refreshStep3Summary();
    }

    // ─── STEP 1: CAPTURE ────────────────────────────────────────────
    function setPreviewStatus(message, isError) {
        const el = document.getElementById('capture-preview-status');
        el.textContent = message;
        el.style.color = isError ? 'var(--crit-text)' : 'var(--text-muted)';
    }

    async function refreshCameraPreview(manual = false) {
        if (previewBusy) return;
        previewBusy = true;
        if (manual) setPreviewStatus('Refreshing preview...', false);

        try {
            const res = await fetch('/api/session/camera/preview?ts=' + Date.now(), { cache: 'no-store' });
            if (!res.ok) {
                let msg = 'Preview unavailable';
                try {
                    const err = await res.json();
                    msg = err.detail || err.error || msg;
                } catch (_) {
                    // no-op
                }
                setPreviewStatus('Preview error: ' + msg, true);
                return;
            }

            const blob = await res.blob();
            if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
            previewObjectUrl = URL.createObjectURL(blob);
            const preview = document.getElementById('capture-preview');
            preview.innerHTML = `<img src="${previewObjectUrl}" alt="Live camera preview">`;
            setPreviewStatus('Live preview updated at ' + new Date().toLocaleTimeString(), false);
        } catch (e) {
            setPreviewStatus('Preview error: ' + e.message, true);
        } finally {
            previewBusy = false;
        }
    }

    function startCameraPreviewLoop() {
        if (previewTimer) return;
        refreshCameraPreview(false);
        previewTimer = setInterval(() => {
            refreshCameraPreview(false);
        }, 2500);
    }

    function stopCameraPreviewLoop() {
        if (previewTimer) {
            clearInterval(previewTimer);
            previewTimer = null;
        }
    }

    async function capturePhoto() {
        const btn = document.getElementById('btn-capture');
        const errEl = document.getElementById('capture-error');
        btn.disabled = true;
        btn.textContent = 'Capturing…';
        errEl.classList.add('hidden');

        try {
            const res = await fetch('/api/session/capture', { method: 'POST' });
            const data = await res.json();
            if (!data.ok) {
                showError(errEl, data.detail || data.error || 'Capture failed');
                return;
            }
            const photo = { ...data.photo, thumbnail_b64: data.thumbnail_b64 };
            photos.push(photo);
            renderPhotoStrip();
            setPreviewStatus('Captured successfully at ' + new Date().toLocaleTimeString(), false);
            refreshCameraPreview(false);
        } catch (e) {
            showError(errEl, 'Network error: ' + e.message);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Capture Photo';
        }
    }

    function renderPhotoStrip() {
        const strip = document.getElementById('photo-strip');
        strip.innerHTML = '';
        photos.forEach(photo => {
            const thumb = document.createElement('div');
            thumb.className = 'photo-thumb';
            const src = photo.thumbnail_b64 || '';
            thumb.innerHTML = src
                ? `<img src="${src}" alt="Photo">`
                : `<div style="width:100%;height:100%;background:rgba(255,255,255,0.05);display:flex;align-items:center;justify-content:center;font-size:0.7rem;color:#64748b">saved</div>`;
            const delBtn = document.createElement('button');
            delBtn.className = 'photo-thumb-delete';
            delBtn.textContent = '×';
            delBtn.title = 'Delete photo';
            delBtn.addEventListener('click', () => deletePhoto(photo.id));
            thumb.appendChild(delBtn);
            strip.appendChild(thumb);
        });
        document.getElementById('photo-count-label').textContent =
            photos.length + ' photo' + (photos.length !== 1 ? 's' : '');
        document.getElementById('btn-step1-next').disabled = photos.length === 0;
    }

    async function deletePhoto(photoId) {
        try {
            const res = await fetch('/api/session/photos/' + photoId, { method: 'DELETE' });
            const data = await res.json();
            if (data.ok) {
                photos = photos.filter(p => p.id !== photoId);
                renderPhotoStrip();
                // Revert preview if no photos remain
                if (photos.length === 0) {
                    document.getElementById('capture-preview').innerHTML =
                        '<span class="capture-placeholder">No photo yet</span>';
                }
            }
        } catch (e) { /* ignore */ }
    }

    function clearPhotos() {
        [...photos].forEach(p => deletePhoto(p.id));
    }

    // ─── STEP 2: MEASURE ────────────────────────────────────────────
    function refreshStep2() {
        setConnStatus(serialConnected);
        updateReadingsDisplay();
    }

    async function connectSerial() {
        const btn = document.getElementById('btn-serial-connect');
        btn.disabled = true;
        btn.textContent = 'Connecting…';
        try {
            const res = await fetch('/api/session/serial/connect', { method: 'POST' });
            const data = await res.json();
            serialConnected = data.ok && data.serial_connected;
            setConnStatus(serialConnected);
        } catch (e) {
            setConnStatus(false);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Connect';
        }
    }

    async function disconnectSerial() {
        if (collecting) stopCollecting();
        try {
            await fetch('/api/session/serial/disconnect', { method: 'POST' });
        } catch (e) { /* ignore */ }
        serialConnected = false;
        setConnStatus(false);
    }

    function setConnStatus(connected) {
        const dot = document.getElementById('conn-dot');
        const label = document.getElementById('conn-label');
        const btnConnect = document.getElementById('btn-serial-connect');
        const btnDisconnect = document.getElementById('btn-serial-disconnect');
        const btnStart = document.getElementById('btn-start-collecting');

        if (connected) {
            dot.className = 'conn-dot connected';
            label.textContent = 'Connected — /dev/ttyACM0';
            btnConnect.classList.add('hidden');
            btnDisconnect.classList.remove('hidden');
            btnStart.disabled = false;
        } else {
            dot.className = 'conn-dot';
            label.textContent = 'Not connected';
            btnConnect.classList.remove('hidden');
            btnDisconnect.classList.add('hidden');
            btnStart.disabled = true;
        }
    }

    function startCollecting() {
        if (collecting) return;
        collecting = true;
        readings = [];
        updateReadingsDisplay();

        document.getElementById('btn-start-collecting').classList.add('hidden');
        document.getElementById('btn-stop-collecting').classList.remove('hidden');

        let lastSeq = 0;
        const target = parseInt(document.getElementById('readings-target').value, 10);

        sseSource = new EventSource('/api/session/readings/stream?last_seq=' + lastSeq);
        sseSource.addEventListener('reading', e => {
            try {
                const frame = JSON.parse(e.data);
                lastSeq = frame.seq || lastSeq;
                readings.push(frame);
                updateLiveRpDisplay(frame);
                updateReadingsDisplay();
                if (readings.length >= target) stopCollecting();
            } catch (err) { /* ignore */ }
        });
        sseSource.onerror = () => {
            if (collecting) {
                document.getElementById('conn-dot').className = 'conn-dot';
                document.getElementById('conn-label').textContent = 'Stream error — reconnecting…';
            }
        };
    }

    function stopCollecting() {
        if (!collecting) return;
        collecting = false;
        if (sseSource) { sseSource.close(); sseSource = null; }
        document.getElementById('btn-start-collecting').classList.remove('hidden');
        document.getElementById('btn-stop-collecting').classList.add('hidden');
        updateReadingsDisplay();
    }

    function updateLiveRpDisplay(frame) {
        document.getElementById('live-rp').textContent =
            frame.rp_ohm != null ? Math.round(frame.rp_ohm).toLocaleString('en-US') : '—';
        document.getElementById('live-current').textContent =
            frame.current_ua != null ? frame.current_ua.toFixed(3) : '—';
        document.getElementById('live-asym').textContent =
            frame.asym_percent != null ? frame.asym_percent.toFixed(1) : '—';

        const badge = document.getElementById('live-status-badge');
        const status = (frame.status || 'UNKNOWN').toUpperCase();
        badge.textContent = status;
        const cls = { EXCELLENT: 'status-healthy', HEALTHY: 'status-healthy',
                      FAIR: 'status-warning', WARNING: 'status-warning',
                      CRITICAL: 'status-critical', SEVERE: 'status-critical' };
        badge.className = 'badge live-badge ' + (cls[status] || 'status-warning');
    }

    function updateReadingsDisplay() {
        const target = parseInt(document.getElementById('readings-target').value, 10);
        const count = readings.length;
        document.getElementById('readings-count').textContent = count + ' collected';
        const pct = Math.min(100, (count / target) * 100);
        document.getElementById('readings-progress-bar').style.width = pct + '%';
        document.getElementById('btn-step2-next').disabled = count < target;
    }

    // ─── STEP 3: ANALYZE ────────────────────────────────────────────
    function refreshStep3Summary() {
        const el = document.getElementById('analyze-summary');
        el.textContent = photos.length + ' photo' + (photos.length !== 1 ? 's' : '') +
                         ' · ' + readings.length + ' reading' + (readings.length !== 1 ? 's' : '');
        const aiEl = document.getElementById('analyze-runtime-status');
        aiEl.textContent = 'AI mode: unknown (run analysis to detect runtime mode)';
        document.getElementById('result-card').classList.add('hidden');
        document.getElementById('analyze-error').classList.add('hidden');
        document.getElementById('analyze-progress').classList.add('hidden');
    }

    function renderAiRuntimeStatus(data) {
        const el = document.getElementById('analyze-runtime-status');
        const runtime = data && data.ai_runtime ? data.ai_runtime : null;
        if (!runtime) {
            el.textContent = 'AI mode: unknown';
            return;
        }
        const modeLabel = runtime.mode === 'gemini_specialists'
            ? 'Gemini specialists'
            : 'Local heuristic fallback';
        const keyLabel = runtime.api_key_present ? 'API key present' : 'API key missing';
        const details = runtime.message ? ' - ' + runtime.message : '';
        el.textContent = 'AI mode: ' + modeLabel + ' (' + keyLabel + ')' + details;
    }

    async function runAnalysis() {
        if (analyzeRunning) return;
        analyzeRunning = true;

        const errEl = document.getElementById('analyze-error');
        errEl.classList.add('hidden');
        document.getElementById('result-card').classList.add('hidden');
        document.getElementById('btn-analyze').disabled = true;
        document.getElementById('btn-step3-back').disabled = true;

        const prog = document.getElementById('analyze-progress');
        prog.classList.remove('hidden');
        let timeoutId = null;

        // Animate progress steps with staggered timing
        const steps = ['prog-sensor', 'prog-vision', 'prog-fusion'];
        steps.forEach(id => document.getElementById(id).classList.remove('done'));

        // Brief visual stagger before actual fetch
        setTimeout(() => document.getElementById('prog-sensor').classList.add('done'), 1000);
        setTimeout(() => document.getElementById('prog-vision').classList.add('done'), 2000);

        try {
            const minReadings = parseInt(document.getElementById('readings-target').value, 10);
            const controller = new AbortController();
            const timeoutMs = 45000;
            timeoutId = setTimeout(() => controller.abort(), timeoutMs);
            const res = await fetch('/api/session/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ min_readings: minReadings }),
                signal: controller.signal,
            });
            clearTimeout(timeoutId);
            const data = await res.json();
            renderAiRuntimeStatus(data);

            document.getElementById('prog-fusion').classList.add('done');
            await delay(400);

            if (!data.ok) {
                showError(errEl, data.detail || data.error || 'Analysis failed');
                return;
            }
            prog.classList.add('hidden');
            renderResult(data);
        } catch (e) {
            if (e && e.name === 'AbortError') {
                showError(errEl, 'Analysis timed out after 45s. Check GOOGLE_API_KEY and server logs, then retry.');
            } else {
                showError(errEl, 'Network error: ' + e.message);
            }
            prog.classList.add('hidden');
        } finally {
            if (timeoutId) clearTimeout(timeoutId);
            analyzeRunning = false;
            document.getElementById('btn-analyze').disabled = false;
            document.getElementById('btn-step3-back').disabled = false;
        }
    }

    function renderResult(data) {
        const fused = data.fused || {};
        const sensor = data.sensor || {};
        const vision = data.vision || {};

        // Big metrics
        const severity = fused.fused_severity_0_to_10 ?? '—';
        const rul = fused.rul_days != null ? fused.rul_days.toFixed(1) : '—';
        const conf = fused.confidence_0_to_1 != null ? Math.round(fused.confidence_0_to_1 * 100) : '—';

        const sevEl = document.getElementById('res-severity');
        sevEl.textContent = typeof severity === 'number' ? severity.toFixed(1) : severity;
        sevEl.style.color = severity >= 7.5 ? 'var(--crit-text)' :
                            severity >= 4.0 ? 'var(--warn-text)' : 'var(--ok-text)';
        document.getElementById('res-rul').textContent = rul;
        document.getElementById('res-confidence').textContent = conf;

        // Badges
        const badgesEl = document.getElementById('result-badges');
        badgesEl.innerHTML = '';
        const addBadge = (text, cls) => {
            const b = document.createElement('div');
            b.className = 'badge ' + cls;
            b.textContent = text;
            badgesEl.appendChild(b);
        };
        if (vision.rust_coverage_band) addBadge('Rust: ' + vision.rust_coverage_band, 'status-warning');
        if (vision.morphology_class)   addBadge('Morph: ' + vision.morphology_class, 'status-warning');
        if (fused.conflict_detected)   addBadge('Sensor/Vision Conflict', 'status-critical');
        if (fused.degraded_mode)       addBadge('Degraded Mode', 'status-critical');

        // Key findings
        const findingsEl = document.getElementById('result-findings');
        const allFindings = [...(sensor.key_findings || []), ...(vision.key_findings || [])];
        findingsEl.innerHTML = allFindings.length
            ? allFindings.map(f => '• ' + f).join('<br>')
            : '';

        // Rationale
        const rationaleEl = document.getElementById('result-rationale');
        rationaleEl.textContent = fused.rationale || '';

        // RUL CI if available
        const ci = fused.rul_confidence_interval_days;
        if (ci) {
            const rulEl = document.getElementById('res-rul');
            rulEl.title = `CI: ${ci.low.toFixed(0)}–${ci.high.toFixed(0)} days`;
        }

        document.getElementById('result-card').classList.remove('hidden');
    }

    function newSession() {
        photos = [];
        readings = [];
        serialConnected = false;
        collecting = false;
        if (sseSource) { sseSource.close(); sseSource = null; }
        fetch('/api/session/new', { method: 'POST' }).catch(() => {});
        renderPhotoStrip();
        document.getElementById('capture-preview').innerHTML =
            '<span class="capture-placeholder">Loading camera preview...</span>';
        setPreviewStatus('Starting live preview...', false);
        document.getElementById('live-rp').textContent = '—';
        document.getElementById('live-current').textContent = '—';
        document.getElementById('live-asym').textContent = '—';
        document.getElementById('live-status-badge').textContent = '—';
        document.getElementById('result-card').classList.add('hidden');
        document.getElementById('analyze-error').classList.add('hidden');
        document.getElementById('analyze-progress').classList.add('hidden');
        setConnStatus(false);
        goToStep(1);
        refreshCameraPreview(false);
    }

    // ─── HELPERS ────────────────────────────────────────────────────
    function showError(el, msg) {
        el.textContent = msg;
        el.classList.remove('hidden');
    }

    function delay(ms) {
        return new Promise(r => setTimeout(r, ms));
    }

    return { init };
})();
