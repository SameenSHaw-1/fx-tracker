/* ────────────────────────────────────────────────────────────────
 * FX Tracker — Main Application Script
 * ──────────────────────────────────────────────────────────────── */

const CURRENCIES = ['EUR', 'USD', 'THB', 'JPY', 'KRW'];
const BANKS = ['BOC', 'ICBC', 'ABC'];
const BANK_NAMES = { BOC: '中国银行', ICBC: '工商银行', ABC: '农业银行' };
const PRICE_TYPES = ['mid', 'buy', 'sell'];
const PRICE_TYPE_LABELS = { mid: '中间价', buy: '现汇买入', sell: '现汇卖出' };

const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes
let countdownValue = REFRESH_INTERVAL;
let countdownTimer = null;
let chartInstance = null;

// ── State ────────────────────────────────────────────────────────
let state = {
  currentRates: null,
  historyData: [],
  selectedCurrency: 'EUR',
  selectedRange: 'today',
  selectedPriceType: 'mid',
  selectedBanks: new Set(['BOC', 'ICBC', 'ABC']),
  yesterdayMid: {},   // { EUR: 780.0, USD: 724.0, ... } for alert logic
};

// ── Currency symbols ────────────────────────────────────────────
const CURRENCY_SYMBOLS = { EUR: '€', USD: '$', THB: '฿', JPY: '¥', KRW: '₩' };

// ── Utility ──────────────────────────────────────────────────────
function formatTime(isoStr) {
  if (!isoStr) return '--';
  const d = new Date(isoStr);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatDate(isoStr) {
  if (!isoStr) return '--';
  const d = new Date(isoStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function showSpinner(show) {
  document.getElementById('spinner').style.display = show ? 'flex' : 'none';
}

function showError(show, message) {
  const banner = document.getElementById('error-banner');
  banner.style.display = show ? 'flex' : 'none';
  if (message) banner.querySelector('span').textContent = '⚠️ ' + message;
}

function setStatus(status, text) {
  const badge = document.getElementById('status-badge');
  badge.className = `status-badge status-${status}`;
  badge.innerHTML = `● ${text || status}`;
}

// ── Countdown ───────────────────────────────────────────────────
function startCountdown() {
  countdownValue = REFRESH_INTERVAL;
  updateCountdownDisplay();
  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    countdownValue -= 1000;
    if (countdownValue <= 0) {
      refreshData();
    } else {
      updateCountdownDisplay();
    }
  }, 1000);
}

function updateCountdownDisplay() {
  const totalSec = Math.max(0, Math.ceil(countdownValue / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  document.getElementById('countdown').textContent = `${m}:${String(s).padStart(2, '0')}`;
}

// ── Fetch current rates ─────────────────────────────────────────
async function fetchCurrentRates() {
  showSpinner(true);
  setStatus('loading', '加载中...');

  try {
    const resp = await fetch(`data/rates.json?t=${Date.now()}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    state.currentRates = await resp.json();

    // Compute yesterday mid for alert logic
    computeYesterdayMid();

    renderTable();
    renderChart();

    document.getElementById('last-updated').textContent =
      formatTime(state.currentRates.updated_at);

    showError(false);
    setStatus('ok', '正常');
  } catch (e) {
    console.error('Failed to fetch rates:', e);
    showError(true, '数据加载失败：' + e.message);
    setStatus('error', '异常');
  } finally {
    showSpinner(false);
  }
}

function computeYesterdayMid() {
  state.yesterdayMid = {};
  if (!state.currentRates || !state.currentRates.rates) return;
  const rates = state.currentRates.rates;
  // Average mid across all available banks
  for (const currency of CURRENCIES) {
    let sum = 0, count = 0;
    for (const bank of BANKS) {
      const b = rates[bank];
      if (b && b[currency] && b[currency].mid != null) {
        sum += b[currency].mid;
        count++;
      }
    }
    if (count > 0) {
      state.yesterdayMid[currency] = sum / count;
    }
  }
}

// ── Render table ─────────────────────────────────────────────────
function renderTable() {
  const tbody = document.getElementById('rates-body');
  tbody.innerHTML = '';
  const rates = state.currentRates?.rates || {};

  for (const currency of CURRENCIES) {
    const tr = document.createElement('tr');

    // Currency name cell
    const sym = CURRENCY_SYMBOLS[currency] || currency;
    const tdName = document.createElement('td');
    tdName.innerHTML = `<span class="currency-symbol">${sym}</span>${currency}`;
    tr.appendChild(tdName);

    // Bank cells
    for (const bank of BANKS) {
      const bankData = rates[bank];
      for (const ptype of PRICE_TYPES) {
        const td = document.createElement('td');
        const val = bankData?.[currency]?.[ptype];
        if (val == null || bankData?.status === 'error') {
          td.innerHTML = '<span class="cell-null">—</span>';
        } else {
          const display = ptype === 'mid' ? val.toFixed(4) : val.toFixed(2);
          const pctChange = computeChange(currency, ptype, val);
          let cls = 'cell-neutral';
          let arrow = '';
          if (pctChange !== null) {
            if (pctChange >= 0.5) {
              cls = 'cell-rise';
              arrow = '<span class="change-arrow">▲</span>';
            } else if (pctChange <= -0.5) {
              cls = 'cell-fall';
              arrow = '<span class="change-arrow">▼</span>';
            }
          }
          td.innerHTML =
            `<span class="cell-value ${cls}">${display}${arrow}</span>` +
            (pctChange !== null ? `<span class="change-pct ${cls.replace('cell-', 'text-')}">${pctChange >= 0 ? '+' : ''}${pctChange.toFixed(2)}%</span>` : '');
        }
        tr.appendChild(td);
      }
    }

    tbody.appendChild(tr);
  }
}

function computeChange(currency, priceType, currentVal) {
  const yesterday = state.yesterdayMid?.[currency];
  if (yesterday == null || yesterday === 0) return null;
  // For non-mid types, approximate using mid as yesterday reference
  return ((currentVal - yesterday) / yesterday) * 100;
}

// ── Fetch history ────────────────────────────────────────────────
async function fetchHistory(range) {
  const now = new Date();
  let startDate, endDate;

  switch (range) {
    case 'today':
      startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      endDate = now;
      break;
    case '7d':
      startDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      endDate = now;
      break;
    case '1m':
      startDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      endDate = now;
      break;
    case '3m':
      startDate = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
      endDate = now;
      break;
    case '6m':
      startDate = new Date(now.getTime() - 180 * 24 * 60 * 60 * 1000);
      endDate = now;
      break;
    default:
      startDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      endDate = now;
  }

  const dates = [];
  let d = new Date(startDate);
  while (d <= endDate) {
    dates.push(d.toISOString().split('T')[0]);
    d.setDate(d.getDate() + 1);
  }

  const allData = [];
  const promises = dates.map(async dateStr => {
    try {
      const resp = await fetch(`data/history/${dateStr}.json?t=${Date.now()}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (Array.isArray(data)) {
        data.forEach(item => {
          if (item.time) {
            item._date = dateStr;
            allData.push(item);
          }
        });
      }
    } catch {
      // Silently skip missing days
    }
  });

  await Promise.allSettled(promises);

  // Sort by date then time
  allData.sort((a, b) => {
    if (a._date !== b._date) return a._date.localeCompare(b._date);
    return (a.time || '').localeCompare(b.time || '');
  });

  state.historyData = allData;
  renderChart();
}

// ── Render chart ─────────────────────────────────────────────────
function renderChart() {
  const ctx = document.getElementById('rate-chart');
  if (!ctx) return;

  const { selectedCurrency, selectedPriceType, selectedBanks, historyData } = state;
  const key = (bank, currency, type) => `${bank}_${currency}_${type}`;

  // Build datasets
  const datasets = [];
  const bankColors = {
    BOC: '#4f8ef7',
    ICBC: '#f59e0b',
    ABC: '#10b981',
  };

  const activeBanks = [...selectedBanks];

  for (const bank of activeBanks) {
    const labels = [];
    const values = [];

    for (const item of historyData) {
      const val = item[key(bank, selectedCurrency, selectedPriceType)];
      if (val != null) {
        labels.push(`${item._date} ${item.time}`);
        values.push(val);
      }
    }

    if (values.length > 0) {
      datasets.push({
        label: `${BANK_NAMES[bank]}`,
        data: values,
        borderColor: bankColors[bank] || '#888',
        backgroundColor: (bankColors[bank] || '#888') + '20',
        borderWidth: 2,
        pointRadius: values.length > 60 ? 0 : 2,
        pointHoverRadius: 5,
        tension: 0.3,
        fill: false,
      });
    }
  }

  if (chartInstance) {
    chartInstance.destroy();
  }

  if (datasets.length === 0) {
    // Show placeholder
    ctx.width = ctx.parentElement.clientWidth;
    ctx.height = 388;
    const context = ctx.getContext('2d');
    context.clearRect(0, 0, ctx.width, ctx.height);
    context.fillStyle = '#6b7280';
    context.font = '14px Inter, sans-serif';
    context.textAlign = 'center';
    context.fillText('暂无历史数据', ctx.width / 2, ctx.height / 2);
    return;
  }

  chartInstance = new Chart(ctx, {
    type: 'line',
    data: { labels: datasets[0].data.map((_, i) => datasets[0].data.length > 30 && i % 3 !== 0 ? '' : (historyData[i]?._date || '') + ' ' + (historyData[i]?.time || '')), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        legend: {
          labels: {
            color: '#c9cdd5',
            font: { family: 'Inter', size: 12 },
            usePointStyle: true,
            pointStyle: 'circle',
          }
        },
        tooltip: {
          backgroundColor: '#1a1d27',
          titleColor: '#e1e4ea',
          bodyColor: '#c9cdd5',
          borderColor: '#2a2d3a',
          borderWidth: 1,
          padding: 12,
          displayColors: true,
          callbacks: {
            label: function(context) {
              return `${context.dataset.label}: ${context.parsed.y?.toFixed(4) || '--'}`;
            }
          }
        },
      },
      scales: {
        x: {
          ticks: {
            color: '#6b7280',
            font: { size: 11 },
            maxTicksLimit: 12,
            maxRotation: 0,
          },
          grid: {
            color: '#2a2d3a20',
          },
        },
        y: {
          ticks: {
            color: '#6b7280',
            font: { size: 11 },
            callback: v => v?.toFixed(2) || '',
          },
          grid: {
            color: '#2a2d3a40',
          },
        },
      },
    },
  });
}

// ── Refresh data ─────────────────────────────────────────────────
function refreshData() {
  Promise.all([
    fetchCurrentRates(),
    fetchHistory(state.selectedRange),
  ]).then(() => {
    startCountdown();
  });
}

// ── Event bindings ───────────────────────────────────────────────
function bindEvents() {
  // Currency tabs
  document.getElementById('currency-tabs').addEventListener('click', e => {
    if (e.target.classList.contains('tab')) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      e.target.classList.add('active');
      state.selectedCurrency = e.target.dataset.currency;
      renderChart();
    }
  });

  // Time range buttons
  document.getElementById('time-range-btns').addEventListener('click', e => {
    if (e.target.classList.contains('range-btn')) {
      document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      state.selectedRange = e.target.dataset.range;
      fetchHistory(state.selectedRange);
    }
  });

  // Price type toggle
  document.getElementById('price-type-toggle').addEventListener('click', e => {
    if (e.target.classList.contains('type-btn')) {
      document.querySelectorAll('.type-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      state.selectedPriceType = e.target.dataset.type;
      renderChart();
    }
  });

  // Bank checkboxes
  document.getElementById('bank-checkboxes').addEventListener('change', e => {
    if (e.target.type === 'checkbox') {
      if (e.target.checked) {
        state.selectedBanks.add(e.target.value);
      } else {
        state.selectedBanks.delete(e.target.value);
      }
      renderChart();
    }
  });
}

// ── Init ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  bindEvents();
  refreshData();
});
