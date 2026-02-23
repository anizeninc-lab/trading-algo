const WS_URL = "ws://localhost:8000/ws/status";
const API_URL = "http://localhost:8000/api";

let socket = null;

function initWebsocket() {
    socket = new WebSocket(WS_URL);

    socket.onopen = () => {
        document.getElementById('system-health').innerText = "Connected";
        document.getElementById('system-health').style.color = "var(--positive)";
    };

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updateDashboard(data);
    };

    socket.onclose = () => {
        document.getElementById('system-health').innerText = "Disconnected";
        document.getElementById('system-health').style.color = "var(--negative)";
        setTimeout(initWebsocket, 2000); // Reconnect attempt
    };

    socket.onerror = (error) => {
        console.error("WebSocket Error: ", error);
        socket.close();
    };
}

function formatCurrency(val) {
    if (val === undefined || isNaN(val)) return '₹0.00';
    return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR'
    }).format(val);
}

// REST Control Triggers
async function toggleStrategy(name, action) {
    // Action is 'start' or 'stop'
    try {
        const res = await fetch(`${API_URL}/strategy/${name}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action })
        });
        const data = await res.json();
        console.log(`${name} -> ${action}:`, data);
    } catch (err) {
        console.error("API Control Error:", err);
    }
}

// DOM Rendering
function updateDashboard(data) {
    // 1. Update Global Header
    const pnlEl = document.getElementById('global-pnl');
    pnlEl.innerText = formatCurrency(data.global_pnl);
    pnlEl.className = data.global_pnl >= 0 ? "value positive" : "value negative";

    if (data.brokers) {
        const bd = data.brokers;
        // Eg. "Upstox: Connected | ICICI: Disconnected"
        document.getElementById('broker-status').innerText = `Upstox: ${bd.upstox || 'Off'} | ICICIdirect: ${bd.icici || 'Off'}`;
    }

    // 2. Update Grid Cards
    const grid = document.getElementById('strategies-grid');
    grid.innerHTML = ""; // Hard refresh for simplicity in spec

    const tbody = document.getElementById('trade-tbody');
    tbody.innerHTML = "";

    const strategies = data.strategies || {};

    for (const [name, state] of Object.entries(strategies)) {

        const isRunning = state.status === "Running";
        const badgeColor = isRunning ? 'var(--positive)' : (state.status === "Error" ? 'var(--negative)' : 'var(--text-muted)');

        // Render Card
        const cardHtml = `
            <div class="card">
                <div class="card-header">
                    <h3>${name}</h3>
                    <span style="color: ${badgeColor}; font-weight: bold; font-size: 0.8rem">&bull; ${state.status}</span>
                </div>
                
                <div style="margin-top: 10px; margin-bottom: 20px; display: flex; gap: 10px">
                    <button onclick="toggleStrategy('${name}', 'start')" ${isRunning ? 'disabled' : ''} style="padding: 5px 10px; background: var(--positive); border:none; border-radius:4px; cursor:pointer; color:black">Start</button>
                    <button onclick="toggleStrategy('${name}', 'stop')" ${!isRunning ? 'disabled' : ''} style="padding: 5px 10px; background: var(--negative); border:none; border-radius:4px; cursor:pointer; color:white">Stop</button>
                </div>

                <div class="grid-stats">
                    <div class="stat-card">
                        <span class="label">Position</span>
                        <span class="value" style="font-size: 1rem;">${state.current_position || 'Flat'}</span>
                    </div>
                    <div class="stat-card">
                        <span class="label">Active Orders</span>
                        <span class="value" style="font-size: 1rem;">${state.active_orders || 0}</span>
                    </div>
                </div>

                <div class="stat-card" style="margin-top: 15px; align-items: flex-start">
                    <span class="label">Last Signal</span>
                    <span class="value" style="font-size: 0.8rem; color: var(--primary)">${state.last_signal || 'None'}</span>
                </div>
            </div>
        `;
        // Use insertAdjacentHTML or document fragment in production, but innerHTML fits the local lightweight constraint
        grid.innerHTML += cardHtml;

        // Render Table Row Entry (Simple representation of strategy state for the log)
        const row = `
            <tr>
                <td>${new Date().toLocaleTimeString()}</td>
                <td><strong>${name}</strong></td>
                <td><span style="color: ${badgeColor}">${state.status}</span></td>
                <td>${state.current_position}</td>
                <td class="${state.unrealized_pnl >= 0 ? 'positive' : 'negative'}">${formatCurrency(state.unrealized_pnl)}</td>
                <td class="${state.realized_pnl >= 0 ? 'positive' : 'negative'}">${formatCurrency(state.realized_pnl)}</td>
            </tr>
        `;
        tbody.innerHTML += row;
    }
}

// Bootstrap
window.onload = () => {
    initWebsocket();
    // Pre-fetch initial state before websocket hooks up
    fetch(`${API_URL}/status`)
        .then(r => r.json())
        .then(d => updateDashboard(d))
        .catch(e => console.error("Initial load skipped", e));
};
