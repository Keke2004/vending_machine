const $ = (selector) => document.querySelector(selector);
const money = (cents) => (cents / 100).toFixed(2);
const escapeHTML = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
const state = {
  products: [],
  category: '全部饮品',
  selectedId: null,
  balance: 0,
  csrf: '',
  isAdmin: false,
  busy: true,
  pending: null,
  ready: false,
};
let toastTimer;
let checkoutVisible = false;

class APIError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').classList.toggle('error', error);
  $('#toast').hidden = false;
  toastTimer = setTimeout(
    () => {
      $('#toast').hidden = true;
    },
    error ? 6000 : 3500,
  );
}

async function api(path, { method = 'GET', data } = {}) {
  const response = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf },
    credentials: 'same-origin',
    ...(data !== undefined ? { body: JSON.stringify(data) } : {}),
    signal: AbortSignal.timeout(15000),
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new APIError('服务返回异常，请稍后重试。', response.status || 500);
  }
  if (!response.ok)
    throw new APIError(result.error || '操作失败，请稍后重试。', response.status);
  return result;
}

function productDescription(product) {
  // 兼容已有数据库中的英文规格，显示时统一转换成中文。
  const volume = product.subtitle.match(/(\d+)\s*m[lL]/i);
  return `${product.category} · ${volume ? `${volume[1]} 毫升` : product.shape === 'can' ? '罐装' : '瓶装'}`;
}

function drinkArt(product) {
  const name = product.name
    .replace('经典', '')
    .replace('醇香', '')
    .replace('鲜橙果汁', '鲜橙')
    .replace('青柠气泡水', '青柠')
    .replace('葡萄果汁', '葡萄');
  return /* HTML */ `<span
    class="drink ${escapeHTML(product.shape)}"
    style="--drink:${escapeHTML(product.color)}"
    aria-hidden="true"
    ><span class="drink-label"
      ><span class="drink-symbol">${product.shape === 'can' ? '✦' : '◒'}</span
      ><span class="drink-name">${escapeHTML(name)}</span
      ><span class="drink-detail">一口清爽</span></span
    ><span class="drink-size">冰爽好滋味</span></span
  >`;
}

function renderProducts() {
  const products = state.products.filter(
    (p) => state.category === '全部饮品' || p.category === state.category,
  );
  $('#product-count').textContent = `${state.products.length} 款饮品`;
  $('#product-grid').innerHTML = products.length
    ? products
        .map(
          (p) =>
            /* HTML */ ` <button
              class="product-card ${p.id === state.selectedId ? 'selected' : ''}"
              style="--drink:${escapeHTML(p.color)}"
              data-product="${p.id}"
              ${p.stock === 0 ? 'disabled' : ''}
              aria-pressed="${p.id === state.selectedId}"
              aria-label="${escapeHTML(p.name)}，${money(p.price_cents)} 元，${p.stock
                ? `库存 ${p.stock}`
                : '已售罄'}"
            >
              <span class="product-art"
                ><span class="slot-label">${String(p.id).padStart(2, '0')} 号</span
                ><span
                  class="stock-badge ${p.stock === 0
                    ? 'sold'
                    : p.stock <= 3
                      ? 'low'
                      : ''}"
                  >${p.stock === 0
                    ? '暂时售罄'
                    : p.stock <= 3
                      ? `仅剩 ${p.stock} 瓶`
                      : `余 ${p.stock} 瓶`}</span
                >${drinkArt(p)}${p.id === state.selectedId
                  ? '<span class="selected-mark">✓ 已选择</span>'
                  : ''}</span
              >
              <span class="product-details"
                ><span class="product-name">${escapeHTML(p.name)}</span
                ><span class="product-subtitle">${escapeHTML(productDescription(p))}</span
                ><span class="product-bottom"
                  ><span class="price"><small>¥</small>${money(p.price_cents)}</span
                  ><span class="choose-icon"
                    >${!p.stock ? '售罄' : p.id === state.selectedId ? '✓' : '+'}</span
                  ></span
                ></span
              >
            </button>`,
        )
        .join('')
    : '<p class="empty-state">这个分类暂时没有上架的饮品，看看其他分类吧。</p>';
}

function renderCheckout() {
  const p = state.products.find((p) => p.id === state.selectedId);
  const valid = p && p.stock > 0;
  $('#balance').textContent = `¥ ${money(state.balance)}`;
  $('#total').textContent = `¥ ${money(p ? p.price_cents : 0)}`;
  $('#selection').classList.toggle('empty-selection', !p);
  $('#selection').innerHTML = p
    ? /* HTML */ `${drinkArt(p)}
        <div class="selected-copy">
          <h3>${escapeHTML(p.name)}</h3>
          <p>${escapeHTML(productDescription(p))}</p>
          <span>¥ ${money(p.price_cents)} <small>× 1</small></span>
        </div>`
    : /* HTML */ `<div class="selection-placeholder">
          <svg class="icon"><use href="#icon-cup" /></svg>
        </div>
        <p>先选一瓶心动饮品吧</p>
        <span>点击饮品卡片，即可加入选购</span>`;
  $('.total small').textContent = p ? '共 1 件' : '共 0 件';
  const step = !p ? 1 : state.balance < p.price_cents ? 2 : 3;
  document.querySelectorAll('[data-step]').forEach((item) => {
    const number = Number(item.dataset.step);
    item.classList.toggle('current', number === step);
    item.classList.toggle('complete', number < step);
    if (number === step) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  });
  $('#mobile-checkout').hidden = checkoutVisible || (!p && !state.pending);
  $('#mobile-checkout > span').textContent = state.pending
    ? '有一笔操作待确认'
    : p
      ? `${p.name} · ¥ ${money(p.price_cents)}`
      : '';
  let label = !p
    ? '请先选择饮品'
    : !valid
      ? '这款饮品已售罄'
      : state.balance < p.price_cents
        ? `还需投入 ¥ ${money(p.price_cents - state.balance)}`
        : '确认购买 · 模拟出货';
  if (state.pending) label = '重试上一笔未确认操作';
  if (state.busy) label = '正在处理，请稍候…';
  $('#purchase-label').textContent = label;
  $('#purchase').disabled =
    !state.ready ||
    state.busy ||
    (!state.pending && (!valid || state.balance < p.price_cents));
  $('#refund').disabled =
    !state.ready || state.busy || !!state.pending || state.balance === 0;
  document.querySelectorAll('[data-amount]').forEach((button) => {
    button.disabled = !state.ready || state.busy || !!state.pending;
  });
}

async function refresh() {
  const [info, catalog] = await Promise.all([api('/api/session'), api('/api/products')]);
  state.balance = info.balance_cents;
  state.csrf = info.csrf_token;
  state.isAdmin = info.is_admin;
  state.products = catalog.products;
  if (!state.products.some((p) => p.id === state.selectedId)) state.selectedId = null;
  renderProducts();
  renderCheckout();
}

function persistPending(pending) {
  state.pending = pending;
  // 隐私模式禁用存储时，本次页面会话仍可正常使用。
  try {
    if (pending) sessionStorage.setItem('sipgo.pending', JSON.stringify(pending));
    else sessionStorage.removeItem('sipgo.pending');
  } catch {
    /* 不影响投币和购买 */
  }
}

async function walletAction(path, data = {}) {
  if (state.busy || !state.ready) return;
  state.busy = true;
  if (!state.pending)
    persistPending({ path, data: { ...data, request_id: crypto.randomUUID() } });
  const operation = state.pending;
  renderCheckout();
  try {
    const result = await api(operation.path, { method: 'POST', data: operation.data });
    persistPending(null);
    state.balance = result.balance_cents;
    if (operation.path === '/api/purchase') {
      $('#success-product').textContent = `${result.product_name} × 1`;
      $('#success-details').innerHTML = /* HTML */ `<p>
          <span>订单编号</span><strong>${escapeHTML(result.order_id)}</strong>
        </p>
        <p><span>本次支付</span><strong>¥ ${money(result.amount_cents)}</strong></p>
        <p><span>剩余金额</span><strong>¥ ${money(result.balance_cents)}</strong></p>`;
      $('#success-dialog').showModal();
      $('.pickup').classList.add('ready');
      $('#pickup-text').textContent = `${result.product_name} · 模拟出货成功`;
      state.selectedId = null;
    } else if (operation.path === '/api/refund') {
      toast(`已退回 ¥ ${money(result.refunded_cents)}，欢迎下次再来。`);
    } else {
      toast(`已投入 ¥ ${money(result.deposited_cents)}`);
    }
  } catch (error) {
    // 未确认的请求保留同一幂等键，重试不会再次扣款或投币。
    const definitive =
      error instanceof APIError && error.status >= 400 && error.status < 500;
    if (definitive) persistPending(null);
    toast(
      definitive
        ? error.message
        : '请求结果暂未确认，请点击“重试上一笔未确认操作”，不会重复扣款。',
      true,
    );
  } finally {
    try {
      await refresh();
    } catch {
      toast('暂时无法同步最新数据，请检查服务后刷新页面。', true);
    }
    state.busy = false;
    renderCheckout();
  }
}

function renderOrders(orders, target) {
  $(target).innerHTML = orders.length
    ? orders
        .map(
          (order) =>
            /* HTML */ `<div class="order-row">
              <div>
                <strong>${escapeHTML(order.product_name)} × 1</strong
                ><small>${escapeHTML(order.id)}</small
                ><small
                  >${escapeHTML(
                    new Date(order.created_at).toLocaleString('zh-CN', { hour12: false }),
                  )}</small
                >
              </div>
              <span
                >¥ ${money(order.amount_cents)}<small class="order-status"
                  >模拟出货完成</small
                ></span
              >
            </div>`,
        )
        .join('')
    : '<p class="empty-state">还没有订单，第一瓶清爽正在等你。</p>';
}

async function loadOrders() {
  $('#orders-list').innerHTML = '<p class="empty-state">正在读取订单…</p>';
  try {
    renderOrders((await api('/api/orders')).orders, '#orders-list');
  } catch (error) {
    $('#orders-list').innerHTML = /* HTML */ `<p class="empty-state">
      ${escapeHTML(error.message)} 请关闭后重试。
    </p>`;
  }
}

async function loadAdmin() {
  $('#login-form').hidden = state.isAdmin;
  $('#admin-content').hidden = !state.isAdmin;
  if (!state.isAdmin) return;
  const data = await api('/api/admin/dashboard');
  $('#admin-stats').innerHTML = /* HTML */ `<div class="stat">
      <span>累计模拟销售额</span><strong>¥ ${money(data.stats.revenue_cents)}</strong>
    </div>
    <div class="stat">
      <span>累计订单</span><strong>${data.stats.order_count}</strong>
    </div>
    <div class="stat">
      <span>当前总库存（在架）</span
      ><strong
        >${data.products
          .filter((p) => p.active)
          .reduce((sum, p) => sum + p.stock, 0)}</strong
      >
    </div>`;
  $('#admin-products').innerHTML = data.products
    .map(
      (p) =>
        /* HTML */ `<tr data-admin-product="${p.id}">
          <td>${escapeHTML(p.name)}</td>
          <td>
            <input
              type="number"
              class="edit-price"
              min="1"
              max="999"
              step="0.01"
              value="${money(p.price_cents)}"
              aria-label="${escapeHTML(p.name)}单价"
            />
          </td>
          <td>
            <input
              type="number"
              class="edit-stock"
              min="0"
              max="999"
              step="1"
              value="${p.stock}"
              aria-label="${escapeHTML(p.name)}库存"
            />
          </td>
          <td>
            <input
              type="checkbox"
              class="edit-active"
              ${p.active ? 'checked' : ''}
              aria-label="${escapeHTML(p.name)}上架状态"
            />
          </td>
          <td>
            <button
              class="save-product"
              data-save="${p.id}"
            >
              保存
            </button>
          </td>
        </tr>`,
    )
    .join('');
  renderOrders(data.orders, '#admin-orders');
}

$('#categories').addEventListener('click', (event) => {
  const button = event.target.closest('[data-category]');
  if (!button) return;
  state.category = button.dataset.category;
  document.querySelectorAll('[data-category]').forEach((b) => {
    b.classList.toggle('active', b === button);
    b.setAttribute('aria-pressed', String(b === button));
  });
  renderProducts();
});

$('#product-grid').addEventListener('click', (event) => {
  const card = event.target.closest('[data-product]');
  if (!card || card.disabled) return;
  const productId = Number(card.dataset.product);
  state.selectedId = state.selectedId === productId ? null : productId;
  renderProducts();
  renderCheckout();
});

document.querySelectorAll('[data-amount]').forEach((button) => {
  button.addEventListener('click', () =>
    walletAction('/api/deposit', { amount_cents: Number(button.dataset.amount) }),
  );
});
$('#purchase').addEventListener('click', () =>
  walletAction('/api/purchase', { product_id: state.selectedId }),
);
$('#refund').addEventListener('click', () => walletAction('/api/refund'));
$('#mobile-checkout').addEventListener('click', () => {
  $('#checkout').scrollIntoView({
    behavior: matchMedia('(prefers-reduced-motion: reduce)').matches
      ? 'instant'
      : 'smooth',
    block: 'start',
  });
});
$('#orders-open').addEventListener('click', () => {
  $('#orders-dialog').showModal();
  loadOrders();
});
$('#admin-open').addEventListener('click', async () => {
  if (!state.ready) {
    toast('请等待服务连接成功。', true);
    return;
  }
  $('#admin-dialog').showModal();
  try {
    await loadAdmin();
  } catch (error) {
    toast(error.message, true);
  }
});

document.querySelectorAll('[data-close]').forEach((button) => {
  button.addEventListener('click', () => button.closest('dialog').close());
});
document.querySelectorAll('dialog').forEach((dialog) => {
  dialog.addEventListener('click', (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (
      event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      event.clientY < bounds.top ||
      event.clientY > bounds.bottom
    )
      dialog.close();
  });
});

$('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.target.querySelector('button');
  button.disabled = true;
  $('#login-error').textContent = '';
  try {
    await api('/api/admin/login', {
      method: 'POST',
      data: { password: $('#password').value },
    });
    state.isAdmin = true;
    $('#password').value = '';
    await loadAdmin();
  } catch (error) {
    $('#login-error').textContent = error.message;
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$('#logout').addEventListener('click', async () => {
  try {
    await api('/api/admin/logout', { method: 'POST', data: {} });
    state.isAdmin = false;
    await loadAdmin();
  } catch (error) {
    toast(error.message, true);
  }
});

$('#admin-products').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-save]');
  if (!button) return;
  const row = button.closest('tr');
  const price = row.querySelector('.edit-price');
  const stock = row.querySelector('.edit-stock');
  if (!price.reportValidity() || !stock.reportValidity()) return;
  if (!price.value || !stock.value) {
    toast('请填写价格和库存。', true);
    return;
  }
  button.disabled = true;
  button.textContent = '保存中';
  try {
    await api(`/api/admin/products/${button.dataset.save}`, {
      method: 'PATCH',
      data: {
        stock: Number(stock.value),
        price_cents: Math.round(Number(price.value) * 100),
        active: row.querySelector('.edit-active').checked ? 1 : 0,
      },
    });
    toast('饮品信息已保存');
    // 保留其他行尚未保存的编辑内容。
    await refresh();
    const dashboard = await api('/api/admin/dashboard');
    $('#admin-stats .stat:last-child strong').textContent = dashboard.products
      .filter((p) => p.active)
      .reduce((sum, p) => sum + p.stock, 0);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = '保存';
  }
});

async function initialize() {
  renderCheckout();
  try {
    // 先建立会话，再并行读取商品，避免首次请求争用 Cookie。
    const info = await api('/api/session');
    state.csrf = info.csrf_token;
    state.balance = info.balance_cents;
    state.isAdmin = info.is_admin;
    state.products = (await api('/api/products')).products;
    try {
      const pending = JSON.parse(sessionStorage.getItem('sipgo.pending'));
      if (
        pending &&
        ['/api/deposit', '/api/purchase', '/api/refund'].includes(pending.path) &&
        pending.data?.request_id
      )
        state.pending = pending;
    } catch {
      /* 过期或无效的暂存数据不影响初始化 */
    }
    state.ready = true;
    if (state.pending)
      toast('有一笔操作尚未确认，请点击重试，系统会避免重复处理。', true);
    renderProducts();
  } catch (error) {
    $('#product-grid').innerHTML = /* HTML */ `<div class="empty-state">
      暂时连接不到售卖机服务。<br />请确认 Python 程序正在运行，然后刷新页面。
    </div>`;
    toast('连接失败，请确认后端已启动。', true);
  } finally {
    state.busy = false;
    renderCheckout();
  }
}

// 结算区进入视野后收起浮动入口，避免遮住投币和退款按钮。
new IntersectionObserver(
  ([entry]) => {
    checkoutVisible = entry.isIntersecting;
    $('#mobile-checkout').hidden =
      checkoutVisible || (state.selectedId === null && !state.pending);
  },
  { threshold: 0.15, rootMargin: '0px 0px -80px 0px' },
).observe($('#checkout'));

initialize();
