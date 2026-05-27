TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GeoQuery — Request Statistics</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 14px;
      background: #f8fafc;
      color: #1e293b;
      min-height: 100vh;
      padding: 32px 24px;
    }

    .page { max-width: 960px; margin: 0 auto; }

    /* ── Header ── */
    .page-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      margin-bottom: 28px;
      gap: 16px;
      flex-wrap: wrap;
    }
    .page-header h1 { font-size: 22px; font-weight: 700; color: #0f172a; }
    .page-header .subtitle { font-size: 13px; color: #64748b; margin-top: 3px; }
    .badge {
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 4px 12px;
      font-size: 12px;
      color: #64748b;
      white-space: nowrap;
      align-self: flex-start;
    }

    /* ── Status cards ── */
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 28px;
    }
    .card {
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 16px 18px;
      position: relative;
      overflow: hidden;
    }
    .card::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 3px;
    }
    .card-total::before  { background: #94a3b8; }
    .card-completed::before { background: #16a34a; }
    .card-pending::before   { background: #d97706; }
    .card-processing::before { background: #2563eb; }
    .card-error::before     { background: #dc2626; }

    .card-value {
      font-size: 32px;
      font-weight: 700;
      color: #0f172a;
      line-height: 1;
      margin-bottom: 4px;
    }
    .card-label {
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #94a3b8;
      margin-bottom: 6px;
    }
    .card-pct {
      font-size: 13px;
      font-weight: 500;
    }
    .card-total .card-pct { color: #64748b; }
    .card-completed .card-pct  { color: #16a34a; }
    .card-pending   .card-pct  { color: #d97706; }
    .card-processing .card-pct { color: #2563eb; }
    .card-error      .card-pct { color: #dc2626; }

    /* ── Chart panel ── */
    .chart-panel {
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 20px 24px;
    }
    .chart-panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 18px;
      gap: 16px;
      flex-wrap: wrap;
    }
    .chart-title {
      font-size: 15px;
      font-weight: 600;
      color: #0f172a;
    }
    .chart-subtitle {
      font-size: 12px;
      color: #94a3b8;
      margin-top: 2px;
    }
    .chart-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

    /* Segmented toggle */
    .seg-group {
      display: flex;
      border: 1px solid #e2e8f0;
      border-radius: 7px;
      overflow: hidden;
      background: #f8fafc;
    }
    .seg-btn {
      padding: 5px 12px;
      font-size: 12px;
      font-weight: 500;
      color: #64748b;
      background: transparent;
      border: none;
      cursor: pointer;
      transition: background 0.1s, color 0.1s;
      white-space: nowrap;
    }
    .seg-btn:not(:last-child) { border-right: 1px solid #e2e8f0; }
    .seg-btn.active { background: #fff; color: #0f172a; box-shadow: inset 0 0 0 1px #e2e8f0; }
    .seg-btn:hover:not(.active) { background: #f1f5f9; color: #475569; }

    /* Period select */
    select.period-select {
      padding: 5px 28px 5px 10px;
      border: 1px solid #e2e8f0;
      border-radius: 7px;
      font-size: 12px;
      font-weight: 500;
      color: #1e293b;
      background: #f8fafc;
      cursor: pointer;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='11' height='11' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2.5'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 8px center;
    }
    select.period-select:focus { outline: none; border-color: #3b82f6; }

    .chart-container { position: relative; height: 320px; }

    .no-data {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 320px;
      font-size: 13px;
      color: #94a3b8;
    }
  </style>
</head>
<body>
<div class="page">

  <div class="page-header">
    <div>
      <h1>GeoQuery — Request Statistics</h1>
      <div class="subtitle">Usage summary across all submitted requests</div>
    </div>
    <div class="badge" id="generated-badge"></div>
  </div>

  <!-- Status cards -->
  <div class="cards">
    <div class="card card-total">
      <div class="card-label">Total</div>
      <div class="card-value" id="val-total">—</div>
      <div class="card-pct">requests</div>
    </div>
    <div class="card card-completed">
      <div class="card-label">Completed</div>
      <div class="card-value" id="val-completed">—</div>
      <div class="card-pct" id="pct-completed"></div>
    </div>
    <div class="card card-pending">
      <div class="card-label">Pending</div>
      <div class="card-value" id="val-pending">—</div>
      <div class="card-pct" id="pct-pending"></div>
    </div>
    <div class="card card-processing">
      <div class="card-label">Processing</div>
      <div class="card-value" id="val-processing">—</div>
      <div class="card-pct" id="pct-processing"></div>
    </div>
    <div class="card card-error">
      <div class="card-label">Error</div>
      <div class="card-value" id="val-error">—</div>
      <div class="card-pct" id="pct-error"></div>
    </div>
  </div>

  <!-- Chart panel -->
  <div class="chart-panel">
    <div class="chart-panel-header">
      <div>
        <div class="chart-title">Requests Over Time</div>
        <div class="chart-subtitle" id="chart-subtitle"></div>
      </div>
      <div class="chart-controls">
        <div class="seg-group" id="field-toggle">
          <button class="seg-btn active" data-field="submit_time">Submit Time</button>
          <button class="seg-btn"        data-field="complete_time">Complete Time</button>
        </div>
        <select class="period-select" id="period-select">
          <option value="day">Day</option>
          <option value="month" selected>Month</option>
          <option value="year">Year</option>
        </select>
      </div>
    </div>
    <div class="chart-container">
      <canvas id="time-chart"></canvas>
      <div class="no-data" id="no-data-msg" style="display:none">No data for this selection.</div>
    </div>
  </div>

</div>

<script>
  const DATA = __GQ_STATS__;

  let currentField  = 'submit_time';
  let currentPeriod = 'month';
  let chart = null;

  // ── Populate status cards ─────────────────────────────────────────────────
  document.getElementById('generated-badge').textContent = 'Generated: ' + DATA.generated_at;
  document.getElementById('val-total').textContent = DATA.total.toLocaleString();

  const statuses = ['completed', 'pending', 'processing', 'error'];
  for (const s of statuses) {
    const count = DATA.status_counts[s] || 0;
    const pct = DATA.total > 0 ? ((count / DATA.total) * 100).toFixed(1) + '%' : '—';
    document.getElementById('val-' + s).textContent = count.toLocaleString();
    document.getElementById('pct-' + s).textContent = pct;
  }

  // ── Chart ─────────────────────────────────────────────────────────────────
  function getFieldLabel(field) {
    return field === 'submit_time' ? 'Submit Time' : 'Complete Time';
  }
  function getPeriodLabel(period) {
    return period === 'day' ? 'Daily' : period === 'month' ? 'Monthly' : 'Yearly';
  }

  function updateChart() {
    const series = (DATA.time_series[currentField] || {})[currentPeriod] || [];
    const labels = series.map(r => r.date);
    const counts = series.map(r => r.count);
    const canvasEl = document.getElementById('time-chart');
    const noDataEl = document.getElementById('no-data-msg');

    document.getElementById('chart-subtitle').textContent =
      getPeriodLabel(currentPeriod) + ' counts by ' + getFieldLabel(currentField).toLowerCase();

    if (series.length === 0) {
      canvasEl.style.display = 'none';
      noDataEl.style.display = '';
      return;
    }
    canvasEl.style.display = '';
    noDataEl.style.display = 'none';

    if (chart) {
      chart.data.labels = labels;
      chart.data.datasets[0].data = counts;
      chart.update();
    } else {
      const ctx = canvasEl.getContext('2d');
      chart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Requests',
            data: counts,
            backgroundColor: '#3b82f6',
            borderRadius: 3,
            borderSkipped: false,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                title: items => items[0].label,
                label: item => ' ' + item.raw.toLocaleString() + ' request' + (item.raw === 1 ? '' : 's'),
              }
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { font: { size: 11 }, color: '#64748b', maxRotation: 45 }
            },
            y: {
              beginAtZero: true,
              ticks: {
                font: { size: 11 },
                color: '#64748b',
                stepSize: 1,
                callback: v => Number.isInteger(v) ? v : null,
              },
              grid: { color: '#f1f5f9' }
            }
          }
        }
      });
    }
  }

  // ── Controls ──────────────────────────────────────────────────────────────
  document.getElementById('field-toggle').addEventListener('click', e => {
    const btn = e.target.closest('.seg-btn');
    if (!btn) return;
    document.querySelectorAll('#field-toggle .seg-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentField = btn.dataset.field;
    updateChart();
  });

  document.getElementById('period-select').addEventListener('change', e => {
    currentPeriod = e.target.value;
    updateChart();
  });

  updateChart();
</script>
</body>
</html>
"""
