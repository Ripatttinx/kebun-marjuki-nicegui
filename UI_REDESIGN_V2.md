# Kebun Marjuki • Perombakan UI NiceGUI V2

Perubahan ini khusus **lapisan tampilan**. `accounting/models.py`, `forms.py`, `services.py`, `journal_rules.py`, `exports.py`, `vouchers.py`, dan database dalam arsip **tetap sama** dengan source code sebelum redesain.

## Perbaikan

- Sidebar dari baris klik manual menjadi tombol navigasi Native NiceGUI. Ikon, label, status aktif, dan jarak antarmenu teratur. Menu mudah discroll.
- Drawer otomatis jadi menu overlay ketika layar lebih sempit dari 1160px, sehingga konten tidak berdesakan di layar laptop 980–1100px.
- Header dengan identitas brand, judul halaman, akun login, tombol keluar, dan akses ekspor.
- Ruang konten mengikuti lebar yang tersedia, bukan lebar penuh viewport di belakang drawer.
- Warna utama hijau hutan dan lime, latar stone, kartu putih, tipografi sederhana.
- Dashboard mengatur kartu statistik dan dua panel grafik/akses cepat lewat grid responsif.
- Tabel menggunakan area scroll horizontal sendiri agar Neraca Lajur dan laporan kolom banyak tidak merusak layout; tetap ada pencarian, sort, pagination.
- Form akun, pelanggan, produk, dan pengaturan memakai grid adaptif; dialog ekspor dirapikan.
- Login dibuat dua bidang responsif, tanpa file HTML, CSS, atau JavaScript kustom.
- Desain konsisten untuk semua 27 route melalui helper `shell`, `metric`, `datatable`, `form_widgets`, `period_bar`.

## Ganti pada proyek yang sudah berjalan (AMAN UNTUK DATABASE)

1. Hentikan server dengan `Ctrl+C`.
2. Cadangkan `nicegui_app.py` serta `db.sqlite3` yang lama.
3. Salin `nicegui_app.py` dari paket ini untuk **mengganti hanya file tersebut** di folder proyek lokal yang ada `manage.py`.
4. Jangan menimpa `db.sqlite3` milikmu dengan database dari ZIP ini jika sudah berisi transaksi.
5. Jalankan `python nicegui_app.py` dari virtual environment yang sudah aktif.
6. Akses http://127.0.0.1:8080/, kemudian refresh browser dengan `Ctrl+Shift+R`.

**Paket lengkap** dapat digunakan untuk proyek baru. Untuk upgrade proyek lama, gunakan cara mengganti satu file di atas.

## Apa yang perlu dicek di laptop?

Karena lingkungan penyusunan tidak dapat memasang Django/NiceGUI untuk render langsung, pengujian yang sudah dilakukan adalah verifikasi sintaks, AST seluruh 27 route, pemeriksaan fungsi backend dan basis data tidak berubah, dan pemeriksaan struktur paket. Pengujian tampilan aktual dan klik form belum dapat diverifikasi. Setelah dijalankan, cek minimal pada resolusi 1366×768, 1024×768, dan lebar ponsel:

- Sidebar tidak menabrak tulisan, tidak overlap konten, tombol menu dapat membuka dan menutup drawer.
- Dashboard: kartu statistik tampil 2 atau 4 kolom sesuai lebar; panel grafik tidak membuat halaman melebar.
- Jurnal: tombol tambah, detail, hapus; login/logout.
- Neraca Lajur: geser di tabel, bukan menggeser seluruh halaman.
- Form: input serta validasi error Django tetap bekerja.
- Inventory Card: stok FIFO, jurnal otomatis, dan ekspor Excel sesuai data lama.

## Rute master tersembunyi

Daftar Akun: `http://127.0.0.1:8080/accounts`
Kode Pembantu: `http://127.0.0.1:8080/parties`

## Catatan teknis

Python-only berarti UI ditulis lewat NiceGUI (`ui.button`, `ui.card`, `ui.grid`, `ui.table`, dll), bukan membuat frontend HTML/CSS/JS sendiri. Browser tetap memakai teknologi frontend dari NiceGUI sebagai dependensi bawaan.

Mode sinkron Django ORM di event-loop NiceGUI (`DJANGO_ALLOW_ASYNC_UNSAFE`) tetap bukan konfigurasi yang aman untuk server publik multiuser. Versi ini untuk penggunaan lokal/percobaan; tidak mengubah persoalan tersebut.
