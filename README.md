# Daily Shopee Picks

Website statis yang menampilkan rekomendasi produk Shopee Affiliate **yang diriset otomatis setiap hari** lewat **Shopee Affiliate Open API** resmi, lalu di-deploy gratis ke Cloudflare Pages.

```
GitHub Actions (05.00 WIB)
  └─ scripts/generate_daily_picks.py
       ├─ Shopee Affiliate Open API (productOfferV2) ← query di config/research.json
       ├─ filter → dedupe → skor → penalti freshness → seleksi beragam
       └─ tulis data/products.json + data/history/
  └─ git commit & push  →  Cloudflare Pages auto-deploy  →  website terbarui
```

## Isi project

| File | Fungsi |
|---|---|
| `index.html`, `assets/` | Dashboard (cari, filter kategori, urutkan, salin link affiliate) |
| `config/research.json` | **Daftar riset harian**: keyword/kategori, filter, jumlah produk |
| `scripts/shopee_api.py` | Klien Shopee Affiliate Open API (signature SHA256, retry, rate limit) |
| `scripts/generate_daily_picks.py` | Riset → skor → `data/products.json` |
| `scripts/scoring.py` | Rumus skor |
| `data/history/` | Riwayat harian & snapshot penjualan (untuk momentum dan rotasi) |
| `data/import/products.csv` | Sumber cadangan manual bila API belum aktif |
| `.github/workflows/daily-update.yml` | Jadwal harian 05.00 WIB |
| `tests/` | Tes end-to-end dengan mock Shopee API |

## 1. Dapatkan akses Shopee Affiliate Open API

1. Login ke [affiliate.shopee.co.id](https://affiliate.shopee.co.id) dengan akun affiliate yang sudah disetujui.
2. Buka menu **Open API** dan ajukan/aktifkan akses.
3. Catat **App ID** dan **Secret** (API key).

> Jangan pernah menaruh App ID/Secret di file repository. Simpan hanya di GitHub Secrets.

## 2. Simpan kredensial di GitHub

Repository → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `SHOPEE_APP_ID` | App ID kamu |
| `SHOPEE_APP_SECRET` | Secret kamu |

Lalu buka tab **Actions → Generate Daily Product Picks → Run workflow** untuk uji coba pertama. Setelah itu workflow berjalan otomatis setiap hari pukul 05.00 WIB, commit `data/products.json`, dan Cloudflare Pages melakukan deploy ulang.

Kalau secrets belum diisi, workflow otomatis memakai `data/import/products.csv` (mode cadangan). Kalau API error dan tidak ada produk sama sekali, workflow **gagal tanpa menimpa data kemarin**, jadi website tidak pernah kosong.

## 3. Atur riset di `config/research.json`

```json
{"category": "Elektronik", "keyword": "kipas portable"}
{"category": "Top Performing", "list": "top_performing", "sort": "sales", "pages": 2}
{"category": "Komisi Tinggi", "list": "all", "sort": "commission", "ams_only": true}
```

- `category`: label yang tampil di website.
- `keyword`: kata kunci pencarian Shopee.
- `list`: `top_performing` (produk terlaris versi Shopee Affiliate) atau `all`.
- `sort`: `sales`, `commission`, `relevance`, `price_low`, `price_high`.
- `pages` × `limit`: jumlah produk yang diambil per query (default 1 × 50).
- `ams_only`: hanya produk dengan komisi ekstra dari seller (Commission Xtra).
- `product_cat_id`: opsional, filter ID kategori Shopee.

Opsi global: `top_n` (jumlah rekomendasi), `max_per_category`, `max_per_shop`, `filters` (rating, penjualan, harga, komisi minimum, kata terlarang), dan `freshness`.

## 4. Cara kerja skor

| Komponen | Bobot | Keterangan |
|---|---|---|
| Popularitas | 30% | Jumlah terjual (skala log terhadap kandidat terbaik hari itu) |
| Komisi | 30% | 70% persentase komisi + 30% estimasi komisi Rupiah |
| Rating | 20% | Fokus pada rentang 4,0–5,0 |
| Harga | 10% | Titik nyaman Rp20rb–Rp150rb |
| Momentum | 10% | Pertumbuhan penjualan dibanding snapshot sebelumnya (netral bila belum ada data) |

Setelah itu:

- **Freshness**: produk yang sudah tampil dalam 3 hari terakhir dikurangi 7% per kemunculan, supaya daftar berganti setiap hari.
- **Keberagaman**: maksimal 5 produk per kategori dan 2 per toko.

Momentum baru aktif mulai hari kedua, setelah ada snapshot pembanding. Skor adalah alat bantu menyaring kandidat, bukan jaminan penjualan.

## 5. Jalankan di komputer

```bash
# mode CSV (tanpa kredensial)
python scripts/generate_daily_picks.py

# mode API
export SHOPEE_APP_ID=xxxx SHOPEE_APP_SECRET=yyyy
python scripts/generate_daily_picks.py --source api --dry-run   # lihat hasil tanpa menulis file
python scripts/generate_daily_picks.py --source api

# tes
python -m unittest discover -s tests -v
```

Butuh Python 3.10+ saja, tanpa library tambahan. Buka `index.html` lewat local web server (misalnya `python -m http.server`).

## 6. Deploy ke Cloudflare Pages

Framework preset: None · Build command: kosong · Output directory: `/`. Setiap push (termasuk commit harian dari Actions) memicu deploy baru.

## Catatan

- Data diambil dari API resmi Shopee Affiliate, bukan scraping. Scraping situs Shopee melanggar ketentuan dan rawan diblokir.
- `offerLink` dari API sudah berupa link affiliate milikmu, jadi tombol "Lihat produk" langsung terlacak komisinya.
- Harga, stok, dan komisi bisa berubah setelah data diambil.
- GitHub Actions terjadwal bisa terlambat beberapa menit saat antrean padat.
