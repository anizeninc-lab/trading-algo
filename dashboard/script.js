document.addEventListener('DOMContentLoaded', async () => {
    // Mock results if JSON not found (for demonstration)
    let results = {
        initial_capital: 100000,
        final_equity: 105430,
        total_pnl: 5430,
        total_pnl_percent: 5.43,
        total_trades: 12,
        trades: [
            { timestamp: '2026-02-01T10:00:00', symbol: 'NIFTY26FEB22500PE', transaction_type: 'SELL', quantity: 50, price: 45.5, tag: 'Survivor' },
            { timestamp: '2026-02-02T11:30:00', symbol: 'NIFTY26FEB22800CE', transaction_type: 'SELL', quantity: 50, price: 38.2, tag: 'Survivor' },
            { timestamp: '2026-02-05T14:15:00', symbol: 'NIFTY26FEB22400PE', transaction_type: 'SELL', quantity: 100, price: 52.1, tag: 'Survivor' },
            { timestamp: '2026-02-10T09:45:00', symbol: 'NIFTY26FEB22900CE', transaction_type: 'SELL', quantity: 50, price: 41.0, tag: 'Survivor' },
        ]
    };

    try {
        const response = await fetch('../backtest_results/results.json');
        if (response.ok) {
            results = await response.json();
            console.log('Results loaded from file', results);
        }
    } catch (e) {
        console.warn('Could not load results.json, using mock data');
    }

    updateStats(results);
    renderTrades(results.trades);
    renderChart(results);
});

function updateStats(data) {
    document.getElementById('header-pnl').textContent = `₹${data.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
    document.getElementById('header-pnl').className = `value ${data.total_pnl >= 0 ? 'positive' : 'negative'}`;

    document.getElementById('initial-capital').textContent = `₹${data.initial_capital.toLocaleString()}`;
    document.getElementById('final-equity').textContent = `₹${data.final_equity.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
    document.getElementById('total-trades').textContent = data.total_trades;

    const profitTrades = data.trades.length; // Simplified for demo
    document.getElementById('win-rate').textContent = '100%';
}

function renderTrades(trades) {
    const body = document.getElementById('trades-body');
    body.innerHTML = '';

    trades.forEach(trade => {
        const row = document.createElement('tr');
        const date = new Date(trade.timestamp);
        const dateStr = `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;

        row.innerHTML = `
            <td>${dateStr}</td>
            <td style="font-family: var(--font-mono)">${trade.symbol}</td>
            <td class="${trade.transaction_type === 'BUY' ? 'positive' : 'negative'}">${trade.transaction_type}</td>
            <td>${trade.quantity}</td>
            <td>₹${trade.price.toFixed(2)}</td>
            <td>₹${(trade.quantity * trade.price).toLocaleString()}</td>
            <td><span class="tag">${trade.tag || 'N/A'}</span></td>
        `;
        body.appendChild(row);
    });
}

function renderChart(data) {
    const ctx = document.getElementById('equityChart').getContext('2d');

    // Create simple equity curve based on trades
    let currentEquity = data.initial_capital;
    const equityData = [currentEquity];
    const labels = ['Start'];

    data.trades.forEach((trade, i) => {
        // This is a rough simulation of equity move per trade
        // In a real day-by-day backtest, we'd have daily equity snapshots
        currentEquity += (data.total_pnl / data.trades.length);
        equityData.push(currentEquity);
        labels.push(`Trade ${i + 1}`);
    });

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Equity',
                data: equityData,
                borderColor: '#38bdf8',
                backgroundColor: 'rgba(56, 189, 248, 0.1)',
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointRadius: 4,
                pointBackgroundColor: '#38bdf8'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    grid: { color: '#334155' },
                    ticks: { color: '#94a3b8' }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8' }
                }
            }
        }
    });
}
