const DATA_URL = "data/products.json";
const LABELS = {popularitas: "Popularitas", komisi: "Komisi", rating: "Rating", harga: "Harga", momentum: "Momentum"};
const SOURCES = {
  shopee_api: "Live dari Shopee Affiliate API",
  api: "Live dari Shopee Affiliate API",
  csv: "Data impor CSV manual",
  sheet: "Data dari Google Sheets",
};
let allProducts = [];

const rupiah = value => Number(value || 0).toLocaleString("id-ID", {style: "currency", currency: "IDR", maximumFractionDigits: 0});
const safe = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const number = value => Number(value || 0);
const compact = value => number(value).toLocaleString("id-ID", {notation: number(value) >= 10000 ? "compact" : "standard", maximumFractionDigits: 1});
const isHttp = url => /^https?:\/\//i.test(url || "");
const $ = id => document.getElementById(id);

function badges(p) {
  const out = [];
  if (p.is_new) out.push('<span class="badge-flag new">Baru</span>');
  if (number(p.sales_growth_pct) >= 1) out.push(`<span class="badge-flag trend">▲ ${number(p.sales_growth_pct).toFixed(1)}%/hr</span>`);
  if (number(p.discount_rate) > 0) out.push(`<span class="badge-flag disc">-${number(p.discount_rate)}%</span>`);
  return out.length ? `<div class="flags">${out.join("")}</div>` : "";
}

function breakdown(p) {
  const b = p.score_breakdown || {};
  return Object.keys(LABELS).filter(k => k in b).map(k => `${LABELS[k]}: ${b[k]}`).join(" · ");
}

function renderProducts() {
  const category = $("category-filter").value;
  const sort = $("sort-filter").value;
  const q = $("search").value.trim().toLowerCase();
  const products = allProducts.filter(p =>
    (!category || p.category === category) &&
    (!q || `${p.name} ${p.shop_name || ""} ${p.category || ""}`.toLowerCase().includes(q)));
  products.sort((a, b) => {
    if (sort === "commission") return number(b.commission_rate) - number(a.commission_rate);
    if (sort === "commission-amount") return number(b.commission_amount) - number(a.commission_amount);
    if (sort === "sales") return number(b.sales) - number(a.sales);
    if (sort === "trend") return number(b.sales_growth_pct) - number(a.sales_growth_pct);
    if (sort === "price-low") return number(a.price) - number(b.price);
    return number(b.score) - number(a.score);
  });
  $("empty-state").classList.toggle("d-none", products.length !== 0);
  $("product-grid").innerHTML = products.map(p => {
    const image = isHttp(p.image_url)
      ? `<img class="product-image" src="${safe(p.image_url)}" alt="${safe(p.name)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">`
      : `<div class="product-image d-grid place-items-center text-secondary">No image</div>`;
    const link = [p.affiliate_url, p.product_url].find(isHttp) || "#";
    const commission = p.commission_rate
      ? `${number(p.commission_rate)}% komisi${p.commission_amount ? ` (±${rupiah(p.commission_amount)})` : ""}`
      : "Komisi belum tersedia";
    const price = p.price_max ? `${rupiah(p.price)} – ${rupiah(p.price_max)}` : rupiah(p.price);
    const rating = p.rating ? `★ ${number(p.rating)}` : "";
    return `<div class="col-6 col-md-4 col-xl-3">
      <article class="product-card">
        <div class="image-wrap">${image}${badges(p)}</div>
        <div class="product-body">
          <div class="d-flex justify-content-between align-items-center gap-1 mb-2">
            <span class="category-pill">${safe(p.category || "Lainnya")}</span>
            <span class="score-pill" title="${safe(breakdown(p))}">${number(p.score)}/100</span>
          </div>
          <div class="product-title" title="${safe(p.name)}">${safe(p.name)}</div>
          <div class="product-price">${price}</div>
          <div class="meta">${commission}</div>
          <div class="meta">${compact(p.sales)} terjual${rating ? ` · ${rating}` : ""}</div>
          ${p.shop_name ? `<div class="meta shop">🏬 ${safe(p.shop_name)}</div>` : ""}
          <div class="reason">${safe(p.recommendation_reason || "Direkomendasikan berdasarkan kombinasi data produk.")}</div>
          <div class="d-flex gap-2 mt-auto">
            <a class="btn btn-aff btn-sm flex-grow-1" href="${safe(link)}" target="_blank" rel="noopener sponsored">Lihat produk ↗</a>
            <button class="btn btn-outline-secondary btn-sm copy-btn" data-link="${safe(link)}" title="Salin link affiliate">⧉</button>
          </div>
        </div>
      </article>
    </div>`;
  }).join("");
}

function formatDate(iso) {
  if (!iso) return "Belum tersedia";
  const d = new Date(`${iso}T00:00:00+07:00`);
  return isNaN(d) ? iso : d.toLocaleDateString("id-ID", {weekday: "long", day: "numeric", month: "long", year: "numeric"});
}

async function init() {
  try {
    const response = await fetch(`${DATA_URL}?v=${Date.now()}`, {cache: "no-store"});
    if (!response.ok) throw new Error("File data/products.json belum tersedia.");
    const data = await response.json();
    allProducts = data.products || [];
    $("generated-date").textContent = formatDate(data.generated_at);
    $("stat-total").textContent = allProducts.length;
    $("stat-categories").textContent = new Set(allProducts.map(p => p.category).filter(Boolean)).size;
    $("stat-new").textContent = data.new_today ?? allProducts.filter(p => p.is_new).length;
    $("stat-updated").textContent = data.updated_at || "—";
    const sourceLabel = SOURCES[data.source] || "Data riset";
    const detail = data.total_fetched ? ` · ${number(data.total_fetched).toLocaleString("id-ID")} produk diriset` : "";
    $("source-badge").textContent = sourceLabel + detail;
    $("source-badge").classList.toggle("live", data.source === "api");
    $("footer-source").textContent = sourceLabel;
    if (data.weights) {
      $("weights").innerHTML = Object.entries(data.weights).map(([k, v]) => `<span><b>${v}%</b> ${LABELS[k] || k}</span>`).join("");
    }
    const categories = [...new Set(allProducts.map(p => p.category).filter(Boolean))].sort();
    $("category-filter").innerHTML = '<option value="">Semua kategori</option>' + categories.map(c => `<option value="${safe(c)}">${safe(c)}</option>`).join("");
    renderProducts();
    ["category-filter", "sort-filter"].forEach(id => $(id).addEventListener("change", renderProducts));
    $("search").addEventListener("input", renderProducts);
    $("product-grid").addEventListener("click", async e => {
      const btn = e.target.closest(".copy-btn");
      if (!btn) return;
      try {
        await navigator.clipboard.writeText(btn.dataset.link);
        btn.textContent = "✓";
      } catch { btn.textContent = "!"; }
      setTimeout(() => (btn.textContent = "⧉"), 1500);
    });
  } catch (error) {
    $("product-grid").innerHTML = `<div class="col-12"><div class="empty-state">${safe(error.message)}<br><small>Jalankan script generator terlebih dahulu. Lihat README.</small></div></div>`;
  }
}
init();
