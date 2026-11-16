# Daily Shopee Picks

Website statis untuk menampilkan rekomendasi produk Shopee Affiliate harian dari data CSV yang kamu impor.

## Isi project

- `index.html`: dashboard produk.
- `data/import/products.csv`: sumber data kandidat produk.
- `scripts/generate_daily_picks.py`: membaca CSV dan menghasilkan 20 produk teratas.
- `scripts/scoring.py`: algoritma scoring awal.
- `data/products.json`: data yang dibaca website.
- `.github/workflows/daily-update.yml`: menjalankan generator setiap hari pukul 05.00 WIB.

## 1. Siapkan data produk

Buka `data/import/products.csv` menggunakan Excel atau Google Sheets. Pertahankan nama kolom berikut:

| Kolom | Wajib? | Keterangan |
|---|---|---|
| name | Ya | Nama produk |
| category | Disarankan | Kategori |
| price | Disarankan | Harga dalam Rupiah, angka saja |
| commission_rate | Disarankan | Persentase komisi, misalnya 8 |
| sales | Disarankan | Jumlah terjual |
| rating | Disarankan | Rating 0–5 |
| review_count | Opsional | Jumlah ulasan |
| image_url | Opsional | URL gambar produk |
| product_url | Disarankan | URL halaman produk |
| affiliate_url | Opsional | Link affiliate milikmu |

Gunakan data yang memang dapat kamu akses dan gunakan sesuai ketentuan Shopee. Jangan menganggap nilai komisi atau penjualan yang kosong sebagai nilai aktual.

## 2. Jalankan generator di komputer

Pastikan Python 3.10+ sudah terpasang. Dari folder project jalankan:

```bash
python scripts/generate_daily_picks.py
```

Script akan memperbarui `data/products.json`. Buka `index.html` melalui local web server (misalnya VS Code Live Server) untuk melihat dashboard. Browser biasanya membatasi `fetch()` dari file lokal `file://`.

## 3. Publish gratis dengan GitHub + Cloudflare Pages

1. Buat repository GitHub baru, misalnya `daily-shopee-picks`.
2. Upload seluruh isi folder project ini ke repository.
3. Masuk ke Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git.
4. Pilih repository tadi.
5. Framework preset: None.
6. Build command: kosongkan.
7. Build output directory: `/` (root project).
8. Deploy. Cloudflare akan memberikan subdomain `*.pages.dev`.

Setiap push ke branch production akan memicu deployment baru.

## 4. Aktifkan pembaruan harian

GitHub Actions sudah disiapkan untuk berjalan pukul 05.00 WIB. Buka tab Actions di repository dan aktifkan workflow bila diminta.

**Penting:** Pada tahap awal, workflow hanya menghitung ulang data dari CSV yang sudah ada. Ia tidak mengambil data baru dari Shopee secara otomatis. Untuk rekomendasi yang benar-benar berubah setiap hari, CSV perlu diperbarui dengan data terbaru atau nantinya kita integrasikan sumber data yang sah/tersedia.

GitHub Actions terjadwal dapat terlambat beberapa menit atau lebih saat antrean padat. Kamu juga bisa menjalankan workflow manual melalui Actions → Generate Daily Product Picks → Run workflow.

## 5. Cara kerja skor awal

- Popularitas/penjualan: 35%
- Komisi: 30%
- Rating: 20%
- Keterjangkauan harga: 15%

Skor dinormalisasi terhadap kandidat yang ada dalam CSV pada saat generator berjalan. Ini adalah baseline untuk membantu menyaring kandidat, bukan prediksi penjualan atau jaminan komisi. Bobot dan rumus sebaiknya dievaluasi setelah tersedia data historis.

## Batasan MVP

- Belum terhubung langsung ke Shopee.
- Belum membuat affiliate link secara otomatis.
- Belum menyimpan data ke database.
- Jangan memasukkan API key, password, atau secret ke file CSV atau repository publik.
