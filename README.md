# Kebun Marjuki Finance & Inventory — NiceGUI Python-Only

## Apa yang berubah?

Proyek asal menggunakan **Django + template HTML + CSS + JavaScript**. Versi ini memakai **Django sebagai backend (model, ORM, database, migrasi, autentikasi, formulir validasi, jasa hitung, aturan jurnal, ekspor Excel)** dan **NiceGUI untuk semua tampilan dan interaksi**, ditulis dalam berkas `nicegui_app.py` dengan Python saja.

Tidak ada file `.html`, `.css`, ataupun `.js` buatan aplikasi dalam paket ini. **Secara teknis browser tetap menjalankan HTML/CSS/JavaScript yang dihasilkan oleh library NiceGUI.** Ini normal, tidak ada framework web browser yang dapat bekerja tanpa teknologi browser tersebut. Developer hanya perlu menulis antarmuka dalam Python, bukan HTML/CSS/JS manual.

> **Penggunaan:** Prototipe **lokal satu komputer / satu server tepercaya**, bukan deployment multiuser di internet. Integrasi Django ORM sinkron dengan NiceGUI di sini menggunakan `DJANGO_ALLOW_ASYNC_UNSAFE` untuk mode lokal. Untuk deployment dengan banyak pengguna, operasi database harus dipindahkan ke worker/thread aman, dan perlu audit kontrol akses serta transaksi.

## Tutorial lengkap Windows 10/11 (VS Code)

1. Pasang **Python 3.12 atau 3.13** dari https://python.org/downloads dan **Visual Studio Code**.
2. Ekstrak ZIP ini. Buka VS Code > **File > Open Folder** dan pilih folder yang langsung mengandung `nicegui_app.py`, `manage.py`, `requirements.txt`.
3. Buka **Terminal > New Terminal** lalu jalankan:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

   Jika aktivasi terblokir oleh PowerShell:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1
   ```
4. Gunakan database yang sudah ada di paket (hasil copy ZIP asli), atau buat database baru. **Backup dulu `db.sqlite3`** jika sudah ada transaksi usaha penting.
5. Terapkan migrasi Django (tidak ada template HTML yang dijalankan):

   ```powershell
   python manage.py migrate
   python manage.py check
   ```

6. Buat akun login Django bila belum punya:

   ```powershell
   python manage.py createsuperuser
   ```

   Bila ingin daftar akun pertanian standar untuk **database baru** tanpa data demo:
   ```powershell
   python manage.py seed_agriculture
   ```
   Jangan jalankan perintah demo bila ingin database bersih. Jangan menggabungkan data demo ke data riil.
7. **Jalankan NiceGUI**, bukan `python manage.py runserver`:

   ```powershell
   python nicegui_app.py
   ```

8. Buka **http://127.0.0.1:8080/** dan login menggunakan username/password Django.

> Kemudian hari cukup `Activate.ps1` dan `python nicegui_app.py`, atau klik `RUN_WINDOWS.bat` setelah `.venv` dibuat.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python nicegui_app.py
```

## Peta menu yang sudah diimplementasi

| Halaman NiceGUI | URL lokal | Sumber logic awal |
| --- | --- | --- |
| Login | `/login` | Django `authenticate()` |
| Dashboard | `/` | `period_totals()` + query jurnal/stock |
| Jurnal Umum | `/journal` | `JournalEntry`, `AutoJournalForm`, jurnal otomatis |
| Tambah Jurnal | `/journal/new` | `build_general_journal`, `voucher_prefix`, `create_stock_movement` |
| Detail / Hapus Jurnal | `/journal/{id}` | `JournalLine`, `delete_journal_entry()` |
| Jurnal Khusus | `/special-journals` | Pengelompokan kode akun debit/kredit lama |
| Produk & Persediaan | `/products` | `Product`, `stock_card()` |
| Form Produk | `/products/new`, `/products/{id}/edit` | `ProductForm`, `create_opening_stock()` |
| Inventory Card FIFO | `/inventory` | `stock_card`, `InventoryLayer` |
| Transaksi FIFO | `/inventory/new` | `MovementForm`, `create_stock_movement()` |
| Buku Besar | `/ledger` | `ledger()` |
| Jurnal Penyesuaian | `/adjustments` | `JournalEntry(kind=ADJUSTMENT)` |
| Input Penyesuaian | `/adjustments/new` | `JournalPairForm`, posting pasangan ke `JournalLine` |
| Buku Besar Pembantu | `/subsidiary` | `subsidiary()` |
| Neraca Saldo | `/trial-balance` | `report_balances()` |
| Neraca Lajur | `/worksheet` | `worksheet()` |
| Laba Rugi | `/income` | `period_totals()` |
| Neraca | `/balance` | `period_totals()` |
| Jurnal Penutup | `/closing-journal` | Query akun nominal dan posting penutup seperti proyek awal |
| Pengaturan Usaha | `/settings` | `ProfileForm`, `BusinessProfile` |
| Daftar Akun | `/accounts` | `AccountForm` |
| Kode Pembantu | `/parties` | `PartyForm` |
| Ekspor Excel semua sheet | Tombol atas **Ekspor Excel** | `accounting.exports.build_linked_workbook()` |

Master **Akun** dan **Kode Pembantu** tetap disembunyikan dari sidebar seperti website asal. Buka langsung alamat `/accounts` dan `/parties` jika diperlukan. Keduanya tetap ikut di-export pada workbook lengkap.

## Struktur penting

- `nicegui_app.py` : Semua halaman, navbar, kartu statistik, grafik, pencarian tabel, formulir interaktif, event klik, ekspor. **100% kode antarmuka buatan kita menggunakan Python NiceGUI**.
- `accounting/models.py` : Skema tabel lama (tidak diubah).
- `accounting/forms.py` : Validasi Django asli (tidak diubah).
- `accounting/services.py` : Buku besar, laporan, FIFO, mutasi dan jurnal terkait (tidak diubah).
- `accounting/journal_rules.py` : Parser keterangan jurnal otomatis, termin dan diskon (tidak diubah).
- `accounting/exports.py` : Excel rumus antarsheet, FIFO (tidak diubah).
- `accounting/vouchers.py` : Nomor bukti otomatis (tidak diubah).
- `accounting/migrations/` dan `accounting/management/` : Migrasi dan seed asli (tidak diubah).
- `config/settings.py` : Konfigurasi Django lama.
- `config/urls.py` : Route Django dikosongkan karena halaman browser ditangani NiceGUI, bukan Django template.
- `db.sqlite3` : Salinan database yang ikut ZIP asli. **Jangan timpa database lokal milikmu tanpa backup.**

## Alur data bisnis tetap sama

- **Jurnal nonstok**: `AutoJournalForm` → `build_general_journal()` → voucher otomatis → `JournalEntry`/`JournalLine` → Buku Besar → Neraca Lajur / Laba Rugi / Neraca.
- **Persediaan**: `MovementForm` → `create_stock_movement()` → FIFO `InventoryLayer`/`InventoryAllocation` + `JournalEntry` otomatis → semua laporan.
- **Jurnal Penyesuaian**: `JournalPairForm` memvalidasi pasangan debet/kredit → simpan dua `JournalLine` per pasangan → buku besar / laporan.
- **Jurnal Khusus**: klasifikasi akun per dokumen dari kode debit/kredit, bukan input ganda.
- **Excel**: workbook sumber yang sama (`accounting.exports`) sebagai proyek Django awal, termasuk rumus antarsheet. `openpyxl` tidak mengkalkulasi hasil formula saat file baru dibuat: pada Excel desktop gunakan **Formulas → Calculation Options → Automatic** dan tekan `Ctrl+Alt+F9` bila hasil pratinjau kosong.

## Pemeriksaan sistem

```powershell
python manage.py check
python manage.py test accounting.tests.test_business_logic
python verify_package.py
```

> Tes antarmuka Django lama dipindahkan menjadi `accounting/tests/legacy_original_django_view_tests.py` untuk dokumentasi dan **tidak dijalankan** karena endpoint HTML lama memang diganti NiceGUI. Tes bisnis sederhana baru memeriksa keseimbangan laporan, stok awal, dan keberadaan rumus Excel. Uji visual dan klik di browser masih diperlukan pada komputermu.

## Kendala umum

- `ModuleNotFoundError: nicegui` → aktifkan `.venv` dan `pip install -r requirements.txt`.
- `No module named django` → dependensi belum terinstal di virtual environment.
- `Address already in use` → port 8080 sedang dipakai. Windows PowerShell: `$env:PORT='8081'; python nicegui_app.py`, lalu buka 8081.
- `no such table` → `python manage.py migrate`.
- Gagal login → gunakan Django superuser: `python manage.py createsuperuser`.
- Browser masih membuka halaman Django lama di port **8000** → versi NiceGUI memakai port **8080**, jalankan `python nicegui_app.py`.
- Excel menampilkan nilai kosong setelah ekspor → buka di Excel desktop, izinkan pengeditan hanya jika file tepercaya, atur kalkulasi otomatis dan hitung ulang.

## Catatan batasan

- Migrasi ini mempertahankan model/validasi/backend, tetapi callback NiceGUI yang baru **belum diuji end-to-end** di lingkungan pembuatan karena pemasangan Django dan NiceGUI tidak tersedia akibat koneksi paket Python terhalang. Kode Python telah melewati pemeriksaan sintaks; tetap lakukan pengujian fungsional di browser sebelum digunakan untuk transaksi riil.
- Untuk akun/produk dengan banyak baris, tabel tersedia fitur filter, sortir, dan pagination; klik baris untuk membuka edit/detail.
- `nicegui_app.py` tidak memakai HTML, CSS, JavaScript, `ui.html`, atau `ui.run_javascript`; antarmuka dibuat lewat `ui.column`, `ui.card`, `ui.table`, `ui.echart`, `ui.button`, dan komponen NiceGUI lain.
- Tidak ada sinkronisasi balik dari Excel ke database. File XLSX adalah snapshot yang dapat dihitung ulang di Excel.

## Login & keselamatan sesi

Sesi NiceGUI ditandatangani memakai secret acak di `.nicegui_secret` (dibuat otomatis pada peluncuran pertama) atau variabel lingkungan `NICEGUI_STORAGE_SECRET`. Jangan membagikan berkas secret. Password tetap diverifikasi oleh `django.contrib.auth.authenticate`.

## Versi 2: Desain workspace modern

Lihat `UI_REDESIGN_V2.md` untuk perubahan visual, cara upgrade dari proyek yang sudah berisi data, dan checklist pengujian. Semua tampilan baru tetap ditulis dalam NiceGUI Python, tanpa file frontend buatan aplikasi. **Agar transaksi lama tidak hilang, untuk upgrade cukup ganti `nicegui_app.py`, jangan menyalin `db.sqlite3` dari ZIP ke proyek lama.**
#   K E B U N - M A R J U K I  
 