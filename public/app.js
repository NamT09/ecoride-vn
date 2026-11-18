const fuelEl = document.getElementById('fuel');
const litersEl = document.getElementById('liters');
const unitEl = document.getElementById('unitPrice');
const totalEl = document.getElementById('total');
const updatedEl = document.getElementById('updatedAt');
const statusEl = document.getElementById('status');
const sourceEl = document.getElementById('source');

const money = n => new Intl.NumberFormat('vi-VN').format(Math.round(n)) + ' đ';
let prices = [];

function formatDate(value) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? 'chưa xác định' : d.toLocaleString('vi-VN');
}

function render() {
  const p = prices.find(x => x.code === fuelEl.value);
  const liters = Number(litersEl.value) || 0;
  if (!p) return;
  unitEl.textContent = money(p.price_vnd) + '/lít';
  totalEl.textContent = money(liters * p.price_vnd);
  updatedEl.textContent = `Hiệu lực: ${formatDate(p.effective_at)} · Kiểm tra: ${formatDate(p.updated_at)}`;
  sourceEl.href = p.source_url;
}

function setPrices(data) {
  prices = data.prices || [];
  if (!prices.length) throw new Error('No prices');
  const previous = fuelEl.value;
  fuelEl.innerHTML = prices.map(p => `<option value="${p.code}">${p.name}</option>`).join('');
  if (prices.some(p => p.code === previous)) fuelEl.value = previous;
  render();

  if (data.refresh_error) {
    statusEl.textContent = 'Đang dùng giá đã lưu; lần kiểm tra nguồn mới chưa thành công.';
  } else if (data.refresh_attempted) {
    statusEl.textContent = 'Đã kiểm tra và đồng bộ giá mới nhất.';
  } else {
    statusEl.textContent = 'Đã tải giá mới nhất.';
  }
}

async function load(forceRefresh = false) {
  try {
    const url = forceRefresh ? '/api/prices?refresh=true' : '/api/prices';
    const r = await fetch(url, { cache: 'no-store' });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || 'API error');
    setPrices(body);
  } catch (e) {
    statusEl.textContent = 'Không tải được giá. Vui lòng thử lại sau.';
    unitEl.textContent = '--';
    totalEl.textContent = '--';
  }
}

fuelEl.addEventListener('change', render);
litersEl.addEventListener('input', render);
load();

// Check periodically while the page is open. Backend also refreshes stale data.
setInterval(() => load(true), 30 * 60 * 1000);
