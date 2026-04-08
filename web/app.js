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
});
