const DATA_URL = "data/products.json";
let allProducts = [];

const rupiah = value => {
  const n = Number(value || 0);
  return n.toLocaleString("id-ID", {style:"currency",currency:"IDR",maximumFractionDigits:0});
};
const safe = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const number = value => Number(value || 0);

function renderProducts() {
  const category = document.getElementById("category-filter").value;
  const sort = document.getElementById("sort-filter").value;
  let products = allProducts.filter(p => !category || p.category === category);
  products.sort((a,b) => {
    if (sort === "commission") return number(b.commission_rate)-number(a.commission_rate);
    if (sort === "sales") return number(b.sales)-number(a.sales);
    if (sort === "price-low") return number(a.price)-number(b.price);
    return number(b.score)-number(a.score);
  });
  const grid = document.getElementById("product-grid");
  document.getElementById("empty-state").classList.toggle("d-none", products.length !== 0);
  grid.innerHTML = products.map((p,i) => {
    const image = p.image_url ? `<img class="product-image" src="${safe(p.image_url)}" alt="${safe(p.name)}" loading="lazy" onerror="this.style.display='none'">` : `<div class="product-image d-grid place-items-center text-secondary">No image</div>`;
    const link = p.affiliate_url || p.product_url || "#";
    const commission = p.commission_rate ? `${number(p.commission_rate)}% komisi` : "Komisi belum tersedia";
    const reason = p.recommendation_reason || "Direkomendasikan berdasarkan kombinasi data produk.";
    return `<div class="col-6 col-md-4 col-xl-3">
      <article class="product-card">
        ${image}
        <div class="product-body">
          <div class="d-flex justify-content-between align-items-center gap-1 mb-2"><span class="category-pill">${safe(p.category || "Lainnya")}</span><span class="score-pill">${number(p.score)}/100</span></div>
          <div class="product-title">${safe(p.name)}</div>
          <div class="product-price">${rupiah(p.price)}</div>
          <div class="meta">${commission} · ${number(p.sales).toLocaleString("id-ID")} terjual</div>
          <div class="reason">${safe(reason)}</div>
          <a class="btn btn-aff btn-sm w-100" href="${safe(link)}" target="_blank" rel="noopener">Lihat produk ↗</a>
        </div>
      </article>
    </div>`;
  }).join("");
}

async function init() {
  try {
    const response = await fetch(`${DATA_URL}?v=${Date.now()}`, {cache:"no-store"});
    if (!response.ok) throw new Error("File data/products.json belum tersedia.");
    const data = await response.json();
    allProducts = data.products || [];
    document.getElementById("generated-date").textContent = data.generated_at || "Belum tersedia";
    document.getElementById("stat-total").textContent = allProducts.length;
    document.getElementById("stat-categories").textContent = new Set(allProducts.map(p=>p.category).filter(Boolean)).size;
    const avg = allProducts.length ? Math.round(allProducts.reduce((s,p)=>s+number(p.score),0)/allProducts.length) : 0;
    document.getElementById("stat-score").textContent = `${avg}/100`;
    document.getElementById("stat-updated").textContent = data.updated_at || "—";
    const categories = [...new Set(allProducts.map(p=>p.category).filter(Boolean))].sort();
    document.getElementById("category-filter").innerHTML = '<option value="">Semua kategori</option>' + categories.map(c=>`<option value="${safe(c)}">${safe(c)}</option>`).join("");
    renderProducts();
    document.getElementById("category-filter").addEventListener("change",renderProducts);
    document.getElementById("sort-filter").addEventListener("change",renderProducts);
  } catch (error) {
    document.getElementById("product-grid").innerHTML = `<div class="col-12"><div class="empty-state">${safe(error.message)}<br><small>Impor data CSV dan jalankan script generator terlebih dahulu. Lihat README.</small></div></div>`;
  }
}
init();
