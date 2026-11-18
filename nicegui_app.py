"""Kebun Marjuki | NiceGUI-only presentation layer.

Semua tampilan dan event ditulis dalam Python: tidak ada template HTML,
berkas CSS, atau berkas JavaScript buatan aplikasi.
Logika bisnis tetap memakai accounting.models/forms/services/journal_rules/exports.

Aplikasi ini disiapkan untuk satu server lokal tepercaya. Django ORM sinkron
berjalan di event loop NiceGUI; DJANGO_ALLOW_ASYNC_UNSAFE dipakai untuk mode
lokal. Jangan gunakan setelan ini untuk deployment multi-user/produksi.
"""
from __future__ import annotations

import os
import secrets
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from collections import defaultdict
from pathlib import Path
from functools import wraps

ROOT = Path(__file__).resolve().parent
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')  # mode lokal, bukan production

import django
django.setup()

from django import forms as djforms
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from fastapi import Request
from nicegui import app, ui

from accounting.forms import (
    AccountForm, PartyForm, ProductForm, ProfileForm, MovementForm,
    AutoJournalForm, JournalPairForm,
)
from accounting.models import (
    Account, BusinessProfile, Party, Product, JournalEntry, JournalLine,
    InventoryLayer, InventoryMovement, ZERO,
)
from accounting.services import (
    ledger, subsidiary, worksheet, report_balances, period_totals, stock_card,
    create_opening_stock, create_stock_movement, delete_journal_entry, money,
)
from accounting.journal_rules import build_general_journal, TERM_SUGGESTIONS
from accounting.vouchers import next_voucher_reference, voucher_prefix
from accounting.exports import build_linked_workbook, NAME, EXPORTS


# --------------------------- UI foundations -------------------------------
# Seluruh tema dibangun dengan NiceGUI + utility classes dari Python.
# Tidak ada file frontend HTML, CSS, atau JavaScript tambahan.
app.colors(primary='#12684A', secondary='#172D26', accent='#C9E86C',
           positive='#16835B', negative='#D84D58', warning='#C99030')

PANEL = 'w-full min-w-0 rounded-2xl border border-stone-200 bg-white shadow-none'
LABEL = 'text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400'
HEADING = 'text-[27px] sm:text-[32px] font-bold tracking-tight text-stone-900 leading-tight'
SUB = 'text-sm leading-relaxed text-stone-500'
INPUT = 'w-full min-w-0'

NAV = [
    ('Overview', [('/', 'Dashboard', 'space_dashboard')]),
    ('Transaksi', [('/journal', 'Jurnal Umum', 'receipt_long'),
                   ('/special-journals', 'Jurnal Khusus', 'view_list'),
                   ('/products', 'Produk & Persediaan', 'agriculture'),
                   ('/inventory', 'Inventory Card · FIFO', 'inventory_2')]),
    ('Buku & Laporan', [('/ledger', 'Buku Besar', 'menu_book'),
                       ('/adjustments', 'Jurnal Penyesuaian', 'edit_note'),
                       ('/subsidiary', 'Buku Besar Pembantu', 'account_tree'),
                       ('/trial-balance', 'Neraca Saldo', 'balance'),
                       ('/worksheet', 'Neraca Lajur', 'table_chart'),
                       ('/income', 'Laba Rugi', 'bar_chart'),
                       ('/balance', 'Neraca', 'account_balance'),
                       ('/closing-journal', 'Jurnal Penutup', 'lock_clock')]),
    ('Preferensi', [('/settings', 'Pengaturan Usaha', 'tune')]),
]


def rupiah(value):
    try:
        amount = Decimal(str(value or '0'))
        sign = '-' if amount < 0 else ''
        return f'{sign}Rp {abs(amount):,.0f}'.replace(',', '.')
    except (InvalidOperation, ValueError):
        return str(value)


def dec(value):
    try:
        return Decimal(str(value or '0').replace(',', '.'))
    except InvalidOperation:
        raise ValidationError('Nominal harus berupa angka.')


def date_or_today(raw):
    try:
        return date.fromisoformat(str(raw or ''))
    except (ValueError, TypeError):
        return timezone.localdate()


def required_date(raw):
    try:
        return date.fromisoformat(str(raw))
    except (ValueError, TypeError):
        raise ValidationError('Tanggal harus valid dengan format YYYY-MM-DD.')


def query_date(request, key='to', default=None):
    raw = request.query_params.get(key, '')
    if not raw:
        return default if default is not None else timezone.localdate()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return default if default is not None else timezone.localdate()


def logged_user():
    uid = app.storage.user.get('uid')
    return get_user_model().objects.filter(pk=uid, is_active=True).first() if uid else None


def guard():
    if logged_user() is None:
        ui.navigate.to('/login')
        return False
    return True


def notify_error(exc):
    if hasattr(exc, 'message_dict'):
        text = '; '.join(f'{key}: {", ".join(map(str, vals))}' for key, vals in exc.message_dict.items())
    elif hasattr(exc, 'messages'):
        text = '; '.join(exc.messages)
    else:
        text = str(exc)
    ui.notify(text[:650], color='negative', multi_line=True, timeout=8000)


def notify_form_errors(form):
    parts = []
    for key, errors in form.errors.items():
        for error in errors:
            parts.append(f'{key if key != "__all__" else "Validasi"}: {error}')
    ui.notify(' | '.join(parts)[:800], color='negative', multi_line=True, timeout=9000)


def action(label, url, *, icon=None, primary=False):
    button = ui.button(label, icon=icon, on_click=lambda: ui.navigate.to(url))
    button.props('unelevated no-caps' if primary else 'flat no-caps')
    button.classes('rounded-xl min-h-10 px-4 text-sm font-semibold ' +
                   ('bg-emerald-800 text-white hover:bg-emerald-900' if primary else
                    'bg-stone-100 text-stone-700 hover:bg-stone-200'))
    return button


def nav_to(url):
    ui.navigate.to(url)


def shell(title, current='/', subtitle='Kelola keuangan kebun secara real time.'):
    """Workspace shell: rapi di desktop, drawer menjadi overlay di laptop kecil.

    Semua markup dideklarasikan memakai komponen NiceGUI langsung di Python.
    Konten halaman ditambahkan sesudah fungsi ini, pada area utama NiceGUI.
    """
    user = logged_user()
    company = BusinessProfile.current()
    ui.page_title(f'{title} | {company.name}')
    ui.query('body').classes('bg-stone-50 text-stone-900')
    # Jangan gunakan max-w-screen yang melebar melewati ruang drawer.
    ui.query('.nicegui-content').classes(
        'w-full min-w-0 max-w-[1540px] mx-auto px-4 sm:px-6 lg:px-8 py-5 lg:py-7 gap-5'
    )

    with ui.header(elevated=False).classes(
        'h-[66px] px-3 sm:px-5 bg-white text-stone-900 border-b border-stone-200 items-center gap-3'
    ):
        ui.button(icon='menu', on_click=lambda: drawer.toggle()).props('flat dense round')\
            .classes('text-stone-700')
        with ui.row().classes('items-center gap-2 min-w-0'):
            with ui.element('div').classes('h-9 w-9 rounded-xl bg-emerald-900 flex items-center justify-center'):
                ui.icon('eco', size='sm').classes('text-lime-200')
            with ui.column().classes('gap-0 min-w-0'):
                ui.label('marjuki.').classes('text-[18px] font-black tracking-tight leading-5')
                ui.label('FINANCE STUDIO').classes('text-[9px] font-bold tracking-[0.20em] text-stone-400')
        ui.separator().props('vertical').classes('mx-2 h-7 hidden md:block')
        ui.label(title).classes('text-sm font-semibold text-stone-600 hidden md:block truncate')
        ui.space()
        ui.label('●  LOCAL WORKSPACE').classes(
            'text-[10px] font-semibold tracking-wider text-emerald-700 hidden lg:block')
        ui.button(icon='file_download', on_click=show_export_dialog)            .props('flat dense round')\
            .classes('text-stone-600').tooltip('Ekspor Excel')
        with ui.row().classes('items-center gap-2'):
            with ui.avatar(color='grey-3', text_color='grey-9', size='32px'):
                ui.label((user.username[:1] if user else 'U').upper()).classes('font-bold')
            ui.label(user.username if user else '').classes('hidden sm:block text-xs font-semibold text-stone-600')
        ui.button(icon='logout', on_click=lambda: (app.storage.user.clear(), ui.navigate.to('/login')))            .props('flat dense round')\
            .classes('text-stone-500').tooltip('Keluar')

    # value=None menggunakan breakpoint otomatis dari layout Quasar.
    with ui.left_drawer(value=None, bordered=False, elevated=False).props(
        'width=258 breakpoint=1160'
    ).classes('bg-[#10291F] text-stone-100 p-0') as drawer:
        with ui.scroll_area().classes('w-full h-full'):
            with ui.column().classes('w-full min-w-0 p-4 gap-0'):
                with ui.row().classes('w-full items-center gap-3 px-2 pt-2 pb-5'):
                    with ui.element('div').classes('h-10 w-10 flex items-center justify-center bg-lime-300 rounded-xl'):
                        ui.icon('spa', size='sm').classes('text-emerald-950')
                    with ui.column().classes('gap-0 min-w-0'):
                        ui.label('Kebun Marjuki').classes('text-base font-bold leading-5 text-white')
                        ui.label('Finance & Inventory').classes('text-[11px] text-emerald-200/70')

                with ui.element('div').classes('w-full rounded-xl bg-white/10 p-3 mb-5'):
                    ui.label('WORKSPACE AKTIF').classes('text-[9px] tracking-widest text-lime-200/70 font-bold')
                    ui.label(company.name).classes('text-[13px] font-semibold text-white mt-1 break-words')

                for group, links in NAV:
                    ui.label(group.upper()).classes(
                        'text-[10px] tracking-[0.15em] font-bold text-emerald-100/40 px-3 mt-4 mb-2'
                    )
                    for path, label, icon in links:
                        active = current == path
                        # Pakai komponen ikon + label terpisah agar tidak bertumpuk.
                        # Tidak memakai tombol dengan icon= dan label sekaligus.
                        with ui.button(on_click=lambda p=path: ui.navigate.to(p)).props(
                            'flat no-caps'
                        ).classes(
                            'w-full min-h-11 px-3 rounded-xl !shadow-none mb-1 '
                            + ('bg-lime-300 text-emerald-950 font-bold' if active else
                               'text-stone-200 hover:bg-white/10')
                        ):
                            with ui.row().classes('w-full min-w-0 flex-nowrap items-center justify-start gap-3'):
                                ui.icon(icon, size='19px').classes('shrink-0')
                                ui.label(label).classes('min-w-0 whitespace-nowrap overflow-hidden text-ellipsis text-left text-[12px]')
                with ui.column().classes('w-full gap-1 mt-6 px-3 pb-5'):
                    ui.separator().classes('opacity-20')
                    ui.label('Pembukuan yang rapi,').classes('text-xs text-emerald-100/50 mt-3')
                    ui.label('keputusan yang tenang.').classes('text-xs text-emerald-100/50')

    # Judul menjadi header konten tunggal, tidak bertabrakan dengan sidebar.
    with ui.row().classes('w-full min-w-0 items-center justify-between gap-4 flex-wrap pb-1'):
        with ui.column().classes('gap-1 min-w-0'):
            ui.label('KEBUN MARJUKI  /  WORKSPACE').classes(
                'text-[10px] font-bold tracking-[0.16em] text-emerald-700'
            )
            ui.label(title).classes(HEADING)
            ui.label(subtitle).classes(SUB)
        ui.button('Unduh laporan', icon='download', on_click=show_export_dialog)            .props('outline no-caps')\
            .classes('rounded-xl px-4 py-2 text-emerald-800 border-emerald-200 font-semibold text-sm')


def section(title, caption='', right=None):
    with ui.row().classes('w-full min-w-0 justify-between items-center gap-3 flex-wrap mb-3'):
        with ui.column().classes('gap-1 min-w-0'):
            ui.label(title).classes('text-[17px] font-bold tracking-tight text-stone-900')
            if caption:
                ui.label(caption).classes('text-xs sm:text-sm text-stone-500')
        if right:
            right()


def metric(label, value, icon, tone='emerald', foot=''):
    palettes = {
        'emerald': ('bg-emerald-50', 'text-emerald-700'),
        'violet': ('bg-violet-50', 'text-violet-700'),
        'amber': ('bg-amber-50', 'text-amber-700'),
        'sky': ('bg-sky-50', 'text-sky-700'),
    }
    bg, fg = palettes.get(tone, palettes['emerald'])
    with ui.card().classes(f'{PANEL} p-4 sm:p-5 gap-3'):
        with ui.row().classes('w-full items-start justify-between gap-3'):
            ui.label(label).classes('text-[12px] font-semibold text-stone-500')
            with ui.element('div').classes(f'h-9 w-9 shrink-0 rounded-xl flex items-center justify-center {bg}'):
                ui.icon(icon, size='20px').classes(fg)
        ui.label(str(value)).classes('text-[24px] sm:text-[27px] font-bold tracking-tight text-stone-900 break-words')
        ui.label(foot or 'Data diperbarui otomatis').classes('text-[11px] text-stone-400')


def datatable(columns, rows, *, search=True, page_size=12, empty='Belum ada data.'):
    """Tabel rapi yang tetap dapat dipakai pada layar kecil dan laporan lebar."""
    normalized = []
    for c in columns:
        if isinstance(c, str):
            normalized.append({'name': c, 'label': c.replace('_', ' ').title(),
                               'field': c, 'align': 'left', 'sortable': True})
        else:
            normalized.append({'name': c[0], 'label': c[1], 'field': c[0],
                               'align': 'right' if len(c) > 2 and c[2] else 'left', 'sortable': True})
    if search:
        with ui.row().classes('w-full items-center justify-between gap-3 mb-4 flex-wrap'):
            search_box = ui.input(placeholder='Cari dalam tabel...')                .props('outlined dense clearable').classes('w-full sm:w-72')
            ui.label(f'{len(rows or [])} data').classes('text-xs text-stone-400')
    # Quasar table dapat lebih lebar dari viewport: cukup area tabel yang scroll.
    with ui.element('div').classes('w-full min-w-0 max-w-full overflow-x-auto rounded-xl border border-stone-200'):
        table = ui.table(columns=normalized, rows=rows or [], row_key='_key',
                         pagination={'rowsPerPage': page_size})            .classes('w-full min-w-[590px] text-[12px]')            .props('flat dense separator=horizontal')
    if search:
        search_box.bind_value(table, 'filter')
    if not rows:
        with ui.row().classes('w-full py-8 justify-center items-center gap-2'):
            ui.icon('inbox').classes('text-stone-400')
            ui.label(empty).classes('text-sm text-stone-500')
    return table


def period_bar(path, to_date, start=None):
    with ui.card().classes(f'{PANEL} p-4'):
        with ui.row().classes('w-full items-end gap-3 flex-wrap'):
            ui.icon('calendar_month', size='sm').classes('text-emerald-700 mb-2 hidden sm:block')
            begin = None
            if start is not None:
                begin = ui.input('Dari tanggal', value=start.isoformat() if start else '')                    .props('outlined dense type=date').classes('w-44')
            until = ui.input('Sampai tanggal', value=to_date.isoformat())                .props('outlined dense type=date').classes('w-44')
            def apply():
                value = f'{path}?to={until.value}'
                if begin and begin.value:
                    value += f'&from={begin.value}'
                ui.navigate.to(value)
            ui.button('Terapkan periode', on_click=apply, icon='filter_alt')                .props('unelevated no-caps').classes('rounded-xl px-4')
            ui.space()
            ui.label('Pilih periode untuk memperbarui data').classes('text-xs text-stone-400 hidden lg:block mb-2')


def download(kind='all', until=None, start=None):
    try:
        end = until or timezone.localdate()
        wb = build_linked_workbook(end, start)
        if kind in EXPORTS:
            wb.active = wb.sheetnames.index(NAME[kind])
        output = BytesIO()
        wb.save(output)
        name = f'kebun_marjuki_{kind}_{end:%Y%m%d}.xlsx'
        ui.download.content(output.getvalue(), filename=name,
                            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        ui.notify('Ekspor Excel dibuat dari transaksi terbaru.', color='positive')
    except Exception as exc:
        notify_error(exc)


def show_export_dialog():
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg p-6 rounded-2xl gap-4'):
        with ui.row().classes('items-center gap-3'):
            with ui.element('div').classes('rounded-xl bg-emerald-50 p-3'):
                ui.icon('file_download', size='md').classes('text-emerald-700')
            with ui.column().classes('gap-1'):
                ui.label('Ekspor laporan').classes('text-lg font-bold text-stone-900')
                ui.label('Workbook Excel dengan rumus antarsheet.').classes(SUB)
        options = {'all': 'Seluruh sheet', **{key: NAME[key] for key in EXPORTS}}
        kind = ui.select(options, value='all', label='Buka sheet pertama')            .props('outlined dense').classes('w-full')
        until = ui.input('Data sampai tanggal', value=timezone.localdate().isoformat())            .props('outlined dense type=date').classes('w-full')
        with ui.row().classes('justify-end w-full gap-2'):
            ui.button('Batal', on_click=dialog.close).props('flat no-caps')
            ui.button('Unduh .xlsx', icon='download',
                      on_click=lambda: download(kind.value, date_or_today(until.value)))                .props('unelevated no-caps').classes('rounded-xl px-4')
    dialog.open()


# -------------------------- login ----------------------------------------
@ui.page('/login')
def login_page():
    ui.page_title('Masuk | Kebun Marjuki')
    ui.query('body').classes('bg-stone-100')
    ui.query('.nicegui-content').classes('p-0 w-full min-h-screen')
    with ui.row().classes('w-full min-h-screen gap-0 items-stretch'):
        with ui.column().classes('hidden lg:flex lg:w-1/2 bg-emerald-950 p-12 xl:p-16 justify-between'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('spa', size='lg').classes('text-lime-300')
                ui.label('marjuki.').classes('font-black text-2xl text-white tracking-tight')
            with ui.column().classes('gap-5 max-w-lg'):
                ui.label('Catatan rapi.\nKebun berkembang.').classes(
                    'text-5xl xl:text-6xl font-bold tracking-tight leading-tight text-white whitespace-pre-line'
                )
                ui.label('Satu ruang kerja untuk jurnal, persediaan, dan laporan yang saling terhubung.')                    .classes('text-lg text-emerald-100/70 leading-relaxed')
                with ui.row().classes('gap-2 mt-3'):
                    for tag in ['JURNAL', 'FIFO', 'LAPORAN']:
                        ui.label(tag).classes('rounded-full border border-white/20 px-3 py-2 text-[10px] tracking-widest font-bold text-lime-200')
            ui.label('KEBUN MARJUKI   /   FINANCE & INVENTORY').classes(
                'text-[10px] text-emerald-200/50 tracking-[0.16em] font-bold')
        with ui.column().classes('w-full lg:w-1/2 min-h-screen justify-center items-center p-5 sm:p-10'):
            with ui.column().classes('w-full max-w-[410px] gap-5'):
                with ui.element('div').classes('h-12 w-12 bg-lime-300 flex items-center justify-center rounded-xl'):
                    ui.icon('spa', size='md').classes('text-emerald-950')
                ui.label('Selamat datang kembali').classes('text-3xl font-bold tracking-tight text-stone-900')
                ui.label('Masuk untuk melanjutkan pembukuan Kebun Marjuki.').classes(SUB)
                username = ui.input('Username').props('outlined autocomplete=username').classes(INPUT)
                password = ui.input('Password', password=True, password_toggle_button=True)                    .props('outlined autocomplete=current-password').classes(INPUT)
                def login():
                    user = authenticate(username=username.value or '', password=password.value or '')
                    if user is None or not user.is_active:
                        ui.notify('Username atau kata sandi tidak sesuai.', color='negative')
                        return
                    app.storage.user['uid'] = user.pk
                    ui.navigate.to('/')
                password.on('keydown.enter', lambda _: login())
                ui.button('Masuk ke workspace', icon='arrow_forward', on_click=login)                    .classes('w-full min-h-12 rounded-xl font-bold')                    .props('unelevated no-caps')
                ui.label('Gunakan akun Django administrator yang sudah dibuat.')                    .classes('text-xs text-stone-400 text-center')


# -------------------------- dashboard ------------------------------------
@ui.page('/')
def dashboard_page(request: Request):
    if not guard():
        return
    end = query_date(request)
    totals = period_totals(end)
    products_count = Product.objects.count()
    stock = InventoryLayer.objects.filter(remaining_quantity__gt=0).aggregate(q=Sum('remaining_quantity'))['q'] or ZERO
    recent = list(JournalEntry.objects.filter(date__lte=end).prefetch_related('lines')\
                  .order_by('-date', '-id')[:8])
    shell('Dashboard', '/', 'Uang, stok, dan laba. Satu tampilan untuk seluruh kebun.')
    with ui.grid(columns='repeat(auto-fit, minmax(208px, 1fr))').classes('w-full gap-3'):
        metric('Total Aset', rupiah(totals['assets']), 'account_balance_wallet', 'emerald')
        metric('Pendapatan', rupiah(totals['revenue']), 'trending_up', 'sky')
        metric('Laba / Rugi', rupiah(totals['profit']), 'insights', 'violet')
        metric('Total Stok', f'{stock:,.3f}'.replace(',', '.') + ' unit', 'inventory_2', 'amber',
               f'{products_count} produk terdaftar')
    period_bar('/', end)
    with ui.grid(columns='repeat(auto-fit, minmax(325px, 1fr))').classes('w-full gap-4'):
        with ui.card().classes(f'{PANEL} p-5'):
            section('Arus aktivitas', 'Tren pendapatan dan pengeluaran dalam 6 bulan')
            labels, revenues, costs = [], [], []
            cursor = end.year * 12 + end.month - 1
            for i in range(5, -1, -1):
                y, mi = divmod(cursor - i, 12)
                month = mi + 1
                labels.append(f'{month:02d}/{y}')
                data = (JournalLine.objects.filter(entry__date__year=y, entry__date__month=month,
                         entry__date__lte=end).values('account__category').annotate(d=Sum('debit'), c=Sum('credit')))
                by_type = {r['account__category']: (r['d'] or ZERO, r['c'] or ZERO) for r in data}
                revenues.append(float(sum((by_type.get(k,(ZERO,ZERO))[1]-by_type.get(k,(ZERO,ZERO))[0]
                                            for k in ('REVENUE','OTHER_INCOME')), ZERO)))
                costs.append(float(sum((by_type.get(k,(ZERO,ZERO))[0]-by_type.get(k,(ZERO,ZERO))[1]
                                         for k in ('COGS','EXPENSE','OTHER_EXPENSE')), ZERO)))
            ui.echart({'tooltip': {'trigger': 'axis'}, 'legend': {'data': ['Pendapatan', 'Biaya'], 'top': '0%', 'left': 'left', 'itemWidth': 12, 'itemHeight': 8, 'textStyle': {'color': '#64748B'}},
                       'grid': {'left': '3%', 'right': '4%', 'top': '15%', 'bottom': '16%', 'containLabel': True},
                       'xAxis': {'type': 'category', 'data': labels, 'axisTick': {'show': False}, 'axisLine': {'show': False}}, 'yAxis': {'type':'value', 'axisLine': {'show': False}, 'axisTick': {'show': False}, 'splitLine': {'lineStyle': {'color': '#E7E5E4'}}},
                       'series': [{'name':'Pendapatan','type':'bar','barMaxWidth':26,'data': revenues,
                                   'itemStyle': {'color':'#059669','borderRadius':[6,6,0,0]}},
                                  {'name':'Biaya','type':'bar','barMaxWidth':26,'data': costs,
                                   'itemStyle': {'color':'#A78BFA','borderRadius':[6,6,0,0]}}]})\
                .classes('h-64 w-full min-w-0')
        with ui.card().classes(f'{PANEL} p-5'):
            section('Akses cepat', 'Lanjutkan pekerjaan tanpa mencari menu')
            for text, icon, path in [
                ('Buat Jurnal Baru','add_circle','/journal/new'),
                ('Jurnal Penyesuaian','edit_note','/adjustments/new'),
                ('Mutasi Persediaan','inventory','/inventory/new'),
                ('Neraca Lajur','table_view','/worksheet'),
            ]:
                ui.button(text, icon=icon, on_click=lambda p=path: ui.navigate.to(p))\
                    .props('flat no-caps align=left').classes('w-full min-h-11 rounded-xl bg-stone-50 text-stone-800')
    with ui.card().classes(f'{PANEL} w-full p-5'):
        section('Jurnal terbaru', 'Histori aktivitas keuangan yang baru tersimpan',
                right=lambda: action('Lihat semua', '/journal', icon='arrow_forward'))
        datatable([('date','Tanggal'),('ref','Nomor Bukti'),('desc','Keterangan'),
                   ('type','Jenis'),('total','Total Debet',True)],
                  [{'_key': x.pk, 'date': x.date.isoformat(), 'ref': x.reference,
                    'desc': x.description[:90], 'type': x.get_kind_display(),
                    'total': rupiah(x.total_debit)} for x in recent])

# ------------------------- django forms -> native NiceGUI ------------------
def form_widgets(form):
    """Use original Django field definitions and validation, but render NiceGUI widgets."""
    widgets = {}
    for name, field in form.fields.items():
        value = form[name].value()
        label = field.label or name.replace('_', ' ').title()
        if isinstance(field, djforms.BooleanField):
            widget = ui.switch(label, value=bool(value))
        elif isinstance(field, djforms.ModelChoiceField):
            options = {str(o.pk): str(o) for o in field.queryset}
            widget = ui.select(options, value=str(value) if value not in (None, '') else None,
                               label=label, with_input=True).props('outlined dense clearable').classes(INPUT)
        elif isinstance(field, djforms.ChoiceField):
            options = {str(code): str(title) for code, title in field.choices}
            widget = ui.select(options, value=str(value) if value not in (None, '') else None,
                               label=label).props('outlined dense').classes(INPUT)
        elif isinstance(field, djforms.DateField):
            iso = value.isoformat() if isinstance(value, date) else str(value or '')
            widget = ui.input(label, value=iso).props('outlined dense type=date').classes(INPUT)
        elif isinstance(field, djforms.DecimalField):
            # Django DecimalField receives exact text, not JavaScript floating point.
            widget = ui.input(label, value=str(value) if value not in (None, '') else '').props('outlined dense inputmode=decimal').classes(INPUT)
        elif isinstance(field, djforms.IntegerField):
            widget = ui.number(label, value=(None if value in (None, '') and not field.required else int(value or 0))).props('outlined dense').classes(INPUT)
        elif isinstance(field.widget, djforms.Textarea):
            widget = ui.textarea(label, value=str(value or '')).props('outlined dense').classes(INPUT)
        else:
            widget = ui.input(label, value=str(value or '')).props('outlined dense').classes(INPUT)
        if field.help_text:
            ui.label(str(field.help_text)).classes('text-xs text-stone-400 -mt-2 mb-1')
        widgets[name] = widget
    return widgets


def collect_values(widgets, bool_names=()):
    return {key: ('on' if obj.value else '') if key in bool_names else
            ('' if obj.value is None else str(obj.value)) for key, obj in widgets.items()}


def crud_form(title, form_cls, model_cls, back, pk=None, *, product=False, help_text=''):
    if not guard():
        return
    instance = model_cls.objects.filter(pk=pk).first() if pk else None
    if pk is not None and instance is None:
        ui.notify('Data tidak ditemukan.', color='negative')
        ui.navigate.to(back)
        return
    shell(title, back, help_text or 'Lengkapi data dan simpan perubahan.')
    form = form_cls(instance=instance)
    with ui.card().classes(f'{PANEL} w-full max-w-4xl p-5 sm:p-7 gap-5'):
        ui.label('Detail informasi').classes('text-lg font-bold')
        with ui.grid(columns='repeat(auto-fit, minmax(225px, 1fr))').classes('w-full gap-4'):
            widgets = form_widgets(form)
        with ui.row().classes('justify-end w-full gap-2'):
            action('Batal', back, icon='close')
            def save():
                data = collect_values(widgets, (n for n,f in form.fields.items()
                                                if isinstance(f, djforms.BooleanField)))
                submitted = form_cls(data, instance=instance)
                if not submitted.is_valid():
                    notify_form_errors(submitted)
                    return
                try:
                    with transaction.atomic():
                        obj = submitted.save()
                        if product and instance is None and submitted.cleaned_data.get('opening_quantity', ZERO) > ZERO:
                            create_opening_stock(obj, submitted.cleaned_data['opening_quantity'],
                                                 submitted.cleaned_data['opening_unit_cost'],
                                                 submitted.cleaned_data['opening_date'])
                    ui.notify('Data berhasil disimpan.', color='positive')
                    ui.navigate.to(back)
                except Exception as exc:
                    notify_error(exc)
            ui.button('Simpan Data', icon='save', on_click=save).props('unelevated no-caps')\
                .classes('rounded-xl px-6')


@ui.page('/accounts')
def accounts_page():
    if not guard(): return
    shell('Daftar Akun', '/accounts', 'Master COA tetap tersedia; tidak muncul di menu utama transaksi.')
    with ui.card().classes(f'{PANEL} w-full p-5'):
        section('Chart of Accounts', 'Kode akun dan saldo awal yang dipakai oleh jurnal dan laporan',
                right=lambda: action('Tambah akun', '/accounts/new', icon='add', primary=True))
        rows = [{'_key': x.pk, 'kode': x.code, 'akun': x.name,
                 'kategori': x.get_category_display(), 'normal':x.normal_balance,
                 'saldo':rupiah(x.opening_balance), 'status':'Aktif' if x.is_active else 'Nonaktif'}
                for x in Account.objects.all()]
        table = datatable(['kode','akun','kategori','normal','saldo','status'], rows)
        table.on('row-click', lambda e: ui.navigate.to(f'/accounts/{e.args[1]["_key"]}/edit'))
        ui.label('Klik baris untuk mengedit. Struktur akun dengan jurnal terikat mengikuti aturan Django Form lama.')\
            .classes('text-xs text-stone-400')


@ui.page('/accounts/new')
def account_new(): crud_form('Tambah Akun', AccountForm, Account, '/accounts')


@ui.page('/accounts/{pk}/edit')
def account_edit(pk: int): crud_form('Ubah Akun', AccountForm, Account, '/accounts', pk)


@ui.page('/parties')
def parties_page():
    if not guard(): return
    shell('Kode Pembantu', '/parties', 'Pelanggan & pemasok untuk piutang dan utang per relasi.')
    with ui.card().classes(f'{PANEL} w-full p-5'):
        section('Daftar relasi', 'Kode pelanggan/pemasok dibuat otomatis dari model aslinya',
                right=lambda: action('Tambah relasi', '/parties/new', icon='person_add', primary=True))
        rows = [{'_key': x.pk, 'kode':x.code, 'nama':x.name, 'jenis':x.get_kind_display(),
                 'awal':rupiah(x.opening_balance), 'telepon':x.phone} for x in Party.objects.all()]
        table = datatable(['kode','nama','jenis','awal','telepon'], rows)
        table.on('row-click', lambda e: ui.navigate.to(f'/parties/{e.args[1]["_key"]}/edit'))


@ui.page('/parties/new')
def party_new(): crud_form('Tambah Pelanggan / Pemasok', PartyForm, Party, '/parties')


@ui.page('/parties/{pk}/edit')
def party_edit(pk: int): crud_form('Ubah Kode Pembantu', PartyForm, Party, '/parties', pk)


@ui.page('/settings')
def settings_page():
    crud_form('Pengaturan Usaha', ProfileForm, BusinessProfile, '/settings',
              pk=BusinessProfile.current().pk,
              help_text='Nama usaha, identitas, dan kode akun otomatis untuk transaksi persediaan.')


@ui.page('/products')
def products_page():
    if not guard(): return
    shell('Produk & Persediaan', '/products', 'Master produk, harga jual, dan kuantitas FIFO tersedia.')
    with ui.card().classes(f'{PANEL} w-full p-5'):
        section('Master komoditas', 'Harga HPP/kg mengikuti lapisan FIFO tertua yang tersedia',
                right=lambda: action('Tambah produk', '/products/new', icon='add', primary=True))
        rows = []
        for product in Product.objects.all():
            card = stock_card(product)
            layer = (InventoryLayer.objects.filter(product=product, remaining_quantity__gt=0)
                     .select_related('movement').order_by('movement__date','movement__id','id').first())
            rows.append({'_key':product.pk, 'kode':product.code, 'produk':product.name, 'satuan':product.unit,
                         'stok':str(card['qty']), 'nilai':rupiah(card['value']),
                         'hpp':rupiah(layer.unit_cost) if layer else '-',
                         'jual':rupiah(product.sale_price),
                         'status':'Aktif' if product.is_active else 'Nonaktif'})
        table = datatable(['kode','produk','satuan','stok','nilai','hpp','jual','status'], rows)
        table.on('row-click', lambda e: ui.navigate.to(f'/products/{e.args[1]["_key"]}/edit'))


@ui.page('/products/new')
def product_new():
    crud_form('Tambah Produk', ProductForm, Product, '/products', product=True,
              help_text='Stok awal hanya untuk produk baru; pastikan saldonya cocok dengan akun Persediaan.')


@ui.page('/products/{pk}/edit')
def product_edit(pk: int):
    crud_form('Ubah Produk', ProductForm, Product, '/products', pk)


# -------------------------- journal auto ---------------------------------
def plan_from_data(data):
    def optional_decimal(key):
        raw = (data.get(key) or '').strip()
        try:
            return Decimal(raw) if raw else None
        except InvalidOperation:
            raise ValidationError(f'{key}: nominal tidak valid.')
    d = date_or_today(data.get('date'))
    return d, build_general_journal(
        data.get('description') or '', optional_decimal('amount'), d,
        term_text=data.get('term_text') or '',
        discount_percent=optional_decimal('discount_percent'), discount_rp=None,
        use_term_discount=str(data.get('use_term_discount', '')).lower() in ('1','true','on'))


@ui.page('/journal')
def journal_page(request: Request):
    if not guard(): return
    end = query_date(request)
    start = query_date(request, 'from', None) if request.query_params.get('from') else None
    qs = JournalEntry.objects.exclude(kind=JournalEntry.Kind.ADJUSTMENT).prefetch_related('lines')\
        .filter(date__lte=end)
    if start:
        qs = qs.filter(date__gte=start)
    entries = list(qs.order_by('-date','-id')[:1000])
    shell('Jurnal Umum', '/journal', 'Input otomatis dari keterangan, persediaan, dan nomor bukti.')
    period_bar('/journal', end, start)
    with ui.card().classes(f'{PANEL} w-full p-5'):
        section('Histori transaksi', 'Klik satu baris untuk melihat detail jurnal',
                right=lambda: action('Buat jurnal', '/journal/new', icon='add', primary=True))
        table = datatable([('tanggal','Tanggal'),('ref','Nomor Bukti'),('uraian','Keterangan'),
                           ('jenis','Jenis'),('debet','Debet',True),('kredit','Kredit',True)],
            [{'_key':x.pk,'tanggal':x.date.isoformat(),'ref':x.reference,
              'uraian':x.description[:95], 'jenis':x.get_kind_display(),
              'debet':rupiah(x.total_debit),'kredit':rupiah(x.total_credit)} for x in entries])
        table.on('row-click', lambda e: ui.navigate.to(f'/journal/{e.args[1]["_key"]}'))


@ui.page('/journal/new')
def journal_new_page():
    if not guard(): return
    shell('Tambah Jurnal Umum', '/journal',
          'Parser jurnal otomatis dari keterangan, nominal, termin, dan transaksi stok.')
    frm = AutoJournalForm(instance=JournalEntry(kind=JournalEntry.Kind.GENERAL))
    with ui.card().classes(f'{PANEL} w-full max-w-5xl p-6 gap-4'):
        ui.label('1. Rincian transaksi').classes('text-lg font-bold')
        with ui.grid(columns=2).classes('w-full gap-4'):
            widgets = form_widgets(frm)
        with ui.card().classes('w-full bg-emerald-50 border border-emerald-100 rounded-2xl p-4 shadow-none'):
            ui.label('Auto Posting Engine').classes('font-bold text-emerald-900')
            ui.label('Jurnal tidak perlu memilih dua akun secara manual: aturan asli menentukan pasangan berdasarkan uraian dan opsi transaksi.').classes('text-sm text-emerald-800')
            ui.label('Contoh: "Bayar beban listrik tunai" dengan nominal 100000. Untuk stok, pilih jenis, produk, kuantitas, dan akun pembayaran.').classes('text-xs text-emerald-700')
        result = ui.column().classes('w-full gap-2')
        def preview():
            result.clear()
            payload = collect_values(widgets, (n for n,f in frm.fields.items() if isinstance(f,djforms.BooleanField)))
            validated = AutoJournalForm(payload, instance=JournalEntry(kind=JournalEntry.Kind.GENERAL))
            if not validated.is_valid():
                notify_form_errors(validated)
                return
            d = validated.cleaned_data
            if d.get('inventory_kind'):
                with result:
                    ui.label('Transaksi stok terdeteksi').classes('text-sm font-bold text-emerald-800')
                    ui.label(f"{d['inventory_product']} · {d['inventory_kind']} · {d['inventory_quantity']} unit")
                    ui.label('Baris akuntansi dan HPP aktual akan dihitung oleh create_stock_movement saat disimpan.').classes(SUB)
                return
            try:
                _, plan = plan_from_data(payload)
                with result:
                    ui.label(f'Pratinjau: {plan.type} | D {rupiah(plan.total_debit)} = K {rupiah(plan.total_credit)}')\
                        .classes('text-emerald-800 font-semibold')
                    datatable([('akun','Akun'),('debet','Debet'),('kredit','Kredit')],
                              [{'_key':i, 'akun':f"{x['account'].code} · {x['account'].name}",
                                'debet':rupiah(x['debit']), 'kredit':rupiah(x['credit'])}
                               for i,x in enumerate(plan.lines)], search=False)
            except ValidationError as exc:
                notify_error(exc)
        # NiceGUI events are Python callbacks; preview also updates after field focus leaves.
        def preview_if_ready():
            desc_value = widgets['description'].value or ''
            has_amount = bool(widgets['amount'].value)
            has_stock = bool(widgets['inventory_kind'].value)
            if str(desc_value).strip() and (has_amount or has_stock):
                preview()
        widgets['description'].on('blur', preview_if_ready)
        widgets['amount'].on('blur', preview_if_ready)
        with ui.row().classes('w-full justify-end gap-3'):
            action('Batal', '/journal')
            ui.button('Pratinjau jurnal', icon='visibility', on_click=preview).props('outline no-caps')
            def save():
                payload = collect_values(widgets, (n for n,f in frm.fields.items() if isinstance(f,djforms.BooleanField)))
                validated = AutoJournalForm(payload, instance=JournalEntry(kind=JournalEntry.Kind.GENERAL))
                if not validated.is_valid():
                    notify_form_errors(validated)
                    return
                try:
                    d = validated.cleaned_data
                    if d.get('inventory_kind'):
                        kind = d['inventory_kind']
                        settlement = d['settlement_account']
                        prefix = voucher_prefix([], movement_kind=kind, settlement_code=settlement.code)
                        ref = next_voucher_reference(prefix)
                        price = d['inventory_product'].sale_price if kind=='OUT' else d['inventory_unit_price']
                        movement = create_stock_movement(
                            product=d['inventory_product'], date_value=d['date'], reference=ref,
                            kind=kind, quantity=d['inventory_quantity'], unit_price=price,
                            settlement_account=settlement, description=d['description'],
                            party=d.get('inventory_party'), user=logged_user())
                        ui.notify('Transaksi FIFO dan jurnal berhasil disimpan.', color='positive')
                        ui.navigate.to(f'/journal/{movement.entry_id}')
                    else:
                        _, plan = plan_from_data(payload)
                        if (plan.type == 'purchase' and any(x['account'].code=='1150' for x in plan.lines)) or (
                            plan.type == 'sale' and any(x['account'].code=='4110' for x in plan.lines)):
                            raise ValidationError('Transaksi stok wajib menggunakan jenis persediaan, produk, dan kuantitas agar FIFO tercatat.')
                        with transaction.atomic():
                            entry = validated.save(commit=False)
                            entry.kind = JournalEntry.Kind.GENERAL
                            entry.created_by = logged_user()
                            entry.reference = next_voucher_reference(voucher_prefix(plan.lines))
                            entry.term = plan.term.text if plan.term else ''
                            entry.due_date = plan.due_date
                            entry.discount_amount = plan.discount
                            entry.save()
                            for item in plan.lines:
                                line = JournalLine(entry=entry, account=item['account'],party=item['party'],
                                                   description=entry.description, debit=item['debit'],credit=item['credit'])
                                line.full_clean()
                                line.save()
                        ui.notify('Jurnal umum berhasil diposting.', color='positive')
                        ui.navigate.to(f'/journal/{entry.pk}')
                except (ValidationError, IntegrityError) as exc:
                    notify_error(exc)
            ui.button('Simpan Jurnal', icon='done_all', on_click=save)\
                .props('unelevated no-caps').classes('rounded-xl')


@ui.page('/journal/{pk}')
def journal_detail_page(pk: int):
    if not guard(): return
    entry = (JournalEntry.objects.filter(pk=pk).prefetch_related('lines__account','lines__party').first())
    if not entry:
        ui.navigate.to('/journal')
        return
    shell(f'Jurnal {entry.reference}', '/adjustments' if entry.kind=='ADJUSTMENT' else '/journal',
          entry.description)
    with ui.card().classes(f'{PANEL} w-full p-5 gap-4'):
        with ui.row().classes('items-center justify-between w-full flex-wrap'):
            with ui.column().classes('gap-1'):
                ui.label(f'{entry.reference} · {entry.date.isoformat()}').classes('font-bold text-lg')
                ui.chip(entry.get_kind_display(), color='green-1', text_color='green-9').props('dense')
            def confirm_delete():
                with ui.dialog() as dlg, ui.card().classes('w-full max-w-lg p-5 rounded-2xl'):
                    ui.label('Hapus jurnal ini?').classes('text-xl font-bold')
                    ui.label('Jika berasal dari stok FIFO, mutasi yang lebih baru mungkin harus dihapus dulu.').classes(SUB)
                    with ui.row().classes('justify-end w-full'):
                        ui.button('Batal', on_click=dlg.close).props('flat no-caps')
                        def perform():
                            try:
                                with transaction.atomic():
                                    delete_journal_entry(entry)
                                ui.notify('Jurnal dan dampaknya berhasil dihapus.', color='positive')
                                ui.navigate.to('/adjustments' if entry.kind=='ADJUSTMENT' else '/journal')
                            except (ValidationError, IntegrityError) as exc:
                                notify_error(exc)
                        ui.button('Ya, hapus', icon='delete', on_click=perform).props('color=negative no-caps')
                dlg.open()
            ui.button('Hapus jurnal', icon='delete', on_click=confirm_delete).props('outline color=negative no-caps')
        datatable([('akun','Akun'),('relasi','Relasi'),('uraian','Uraian'),
                   ('debet','Debet',True),('kredit','Kredit',True)],
                  [{'_key':l.pk, 'akun':str(l.account), 'relasi':str(l.party or '-'),
                    'uraian':l.description,'debet':rupiah(l.debit) if l.debit else '-',
                    'kredit':rupiah(l.credit) if l.credit else '-'} for l in entry.lines.all()], search=False)
        with ui.row().classes('gap-4 justify-end w-full'):
            ui.label(f'Total Debet {rupiah(entry.total_debit)}').classes('font-semibold')
            ui.label(f'Total Kredit {rupiah(entry.total_credit)}').classes('font-semibold')


@ui.page('/adjustments')
def adjustments_page(request: Request):
    if not guard(): return
    end = query_date(request)
    start = query_date(request,'from',None) if request.query_params.get('from') else None
    qs = JournalEntry.objects.filter(kind=JournalEntry.Kind.ADJUSTMENT, date__lte=end)\
        .prefetch_related('lines').order_by('-date','-id')
    if start:
        qs = qs.filter(date__gte=start)
    shell('Jurnal Penyesuaian','/adjustments','Penyesuaian saldo dan koreksi akhir periode.')
    period_bar('/adjustments',end,start)
    with ui.card().classes(f'{PANEL} w-full p-5'):
        section('Daftar penyesuaian','Dampaknya langsung diperhitungkan dalam neraca lajur dan buku besar',
                right=lambda: action('Tambah penyesuaian','/adjustments/new', icon='add',primary=True))
        table = datatable([('tanggal','Tanggal'),('bukti','Bukti'),('uraian','Keterangan'),
                           ('nominal','Debet/Kredit',True)],
                          [{'_key':x.pk,'tanggal':x.date.isoformat(),'bukti':x.reference,
                            'uraian':x.description[:100],'nominal':rupiah(x.total_debit)} for x in list(qs[:1000])])
        table.on('row-click',lambda e: ui.navigate.to(f'/journal/{e.args[1]["_key"]}'))


@ui.page('/adjustments/new')
def adjustment_new_page():
    if not guard(): return
    shell('Tambah Jurnal Penyesuaian','/adjustments',
          'Pasangan akun debet/kredit tervalidasi oleh aturan jurnal asli.')
    accounts = {str(x.pk):str(x) for x in Account.objects.filter(is_active=True,is_header=False)}
    customers = {str(x.pk):str(x) for x in Party.objects.filter(kind=Party.Kind.CUSTOMER)}
    suppliers = {str(x.pk):str(x) for x in Party.objects.filter(kind=Party.Kind.SUPPLIER)}
    with ui.card().classes(f'{PANEL} w-full max-w-5xl p-6 gap-4'):
        entry_date = ui.input('Tanggal', value=timezone.localdate().isoformat()).props('outlined dense type=date')
        desc = ui.textarea('Keterangan penyesuaian').props('outlined').classes('w-full')
        ui.label('2. Pasangan jurnal').classes('font-bold text-lg')
        pairs=[]
        container=ui.column().classes('w-full gap-3')
        def add_pair():
            if len(pairs)>=15:
                ui.notify('Maksimal 15 pasangan jurnal.',color='warning')
                return
            with container:
                with ui.card().classes('w-full p-4 border border-stone-200 rounded-2xl shadow-none') as row_card:
                    with ui.grid(columns=2).classes('w-full gap-3'):
                        debit_acct = ui.select(accounts,label='Akun debet',with_input=True).props('outlined').classes('w-full')
                        credit_acct = ui.select(accounts,label='Akun kredit',with_input=True).props('outlined').classes('w-full')
                        amount = ui.input('Nominal (Rp)',value='').props('outlined dense inputmode=decimal').classes('w-full')
                        detail = ui.input('Uraian (opsional)').props('outlined').classes('w-full')
                        dbparty = ui.select(customers,label='Pelanggan untuk debet 1140',with_input=True).props('outlined dense clearable').classes('w-full')
                        crparty = ui.select(suppliers,label='Pemasok untuk kredit 2110',with_input=True).props('outlined dense clearable').classes('w-full')
                    def remove():
                        if len(pairs)<=1:
                            ui.notify('Minimal satu pasangan jurnal.',color='warning')
                            return
                        pairs.remove(record)
                        row_card.delete()
                    ui.button('Hapus pasangan',icon='remove_circle',on_click=remove)\
                        .props('flat color=negative no-caps')
                record={'debit_account':debit_acct,'credit_account':credit_acct,'amount':amount,
                        'description':detail,'debit_party':dbparty,'credit_party':crparty}
                pairs.append(record)
        add_pair()
        ui.button('Tambah pasangan jurnal',icon='add',on_click=add_pair).props('outline no-caps')
        with ui.row().classes('w-full justify-end'):
            action('Batal','/adjustments')
            def save():
                if not desc.value or not str(desc.value).strip():
                    ui.notify('Keterangan wajib diisi.',color='negative');return
                try:
                    when=required_date(entry_date.value)
                except ValidationError as exc:
                    notify_error(exc)
                    return
                validated=[]
                for record in pairs:
                    payload=collect_values(record)
                    form=JournalPairForm(payload)
                    if not form.is_valid():
                        notify_form_errors(form)
                        return
                    validated.append(form.cleaned_data)
                if not validated:
                    ui.notify('Minimal satu pasangan jurnal.',color='negative');return
                try:
                    with transaction.atomic():
                        entry=JournalEntry.objects.create(date=when,description=str(desc.value).strip(),
                            reference=next_voucher_reference('JP'), kind=JournalEntry.Kind.ADJUSTMENT,
                            created_by=logged_user())
                        for r in validated:
                            amt=r['amount']
                            for account,party,d,c in [
                                (r['debit_account'],r.get('debit_party'),amt,ZERO),
                                (r['credit_account'],r.get('credit_party'),ZERO,amt),
                            ]:
                                line=JournalLine(entry=entry,account=account,party=party,
                                    description=r.get('description') or '',debit=d,credit=c)
                                line.full_clean()
                                line.save()
                    ui.notify('Penyesuaian berhasil disimpan.',color='positive')
                    ui.navigate.to(f'/journal/{entry.pk}')
                except (ValidationError,IntegrityError) as exc:
                    notify_error(exc)
            ui.button('Posting penyesuaian',icon='done',on_click=save).props('unelevated no-caps')

# -------------------------- buku besar & laporan ----------------------------
@ui.page('/ledger')
def ledger_page(request: Request):
    if not guard(): return
    shell('Buku Besar','/ledger','Saldo awal dan seluruh mutasi menurut akun.')
    end = query_date(request)
    start = query_date(request,'from',None) if request.query_params.get('from') else None
    account_id = request.query_params.get('account','')
    accounts = {str(x.pk):str(x) for x in Account.objects.filter(is_header=False)}
    with ui.card().classes(f'{PANEL} w-full p-5 gap-4'):
        with ui.row().classes('items-end gap-3 flex-wrap'):
            choice = ui.select(accounts, value=account_id if account_id in accounts else None,
                               label='Pilih akun',with_input=True).props('outlined').classes('w-full sm:w-72')
            begin = ui.input('Dari',value=start.isoformat() if start else '').props('outlined dense type=date').classes('w-44')
            until = ui.input('Sampai',value=end.isoformat()).props('outlined dense type=date').classes('w-44')
            def go():
                path=f'/ledger?account={choice.value or ""}&to={until.value}'
                if begin.value: path+=f'&from={begin.value}'
                ui.navigate.to(path)
            ui.button('Lihat mutasi',on_click=go,icon='search').props('no-caps')
        if account_id in accounts:
            account=Account.objects.get(pk=account_id)
            data=ledger(account,start,end)
            with ui.grid(columns='repeat(auto-fit, minmax(215px, 1fr))').classes('w-full gap-3'):
                metric('Saldo Awal',rupiah(data['opening']),'history')
                metric('Saldo Akhir',rupiah(data['closing']),'payments','sky')
            datatable([('tanggal','Tanggal'),('bukti','Nomor Bukti'),('ket','Keterangan'),('relasi','Relasi'),
                       ('debet','Debet',True),('kredit','Kredit',True),('saldo','Saldo',True)],
                      [{'_key':i,'tanggal':r['date'].isoformat(),'bukti':r['reference'],
                        'ket':r['description'],'relasi':str(r['party'] or '-'),
                        'debet':rupiah(r['debit']), 'kredit':rupiah(r['credit']),
                        'saldo':rupiah(r['balance'])} for i,r in enumerate(data['records'])])
        else:
            ui.label('Pilih akun untuk menampilkan saldo awal, mutasi, dan saldo akhir.').classes(SUB)


@ui.page('/subsidiary')
def subsidiary_page(request: Request):
    if not guard(): return
    shell('Buku Besar Pembantu','/subsidiary','Piutang dan utang terperinci menurut pelanggan/pemasok.')
    end=query_date(request)
    start=query_date(request,'from',None) if request.query_params.get('from') else None
    party_id=request.query_params.get('party','')
    opts={str(x.pk):str(x) for x in Party.objects.all()}
    with ui.card().classes(f'{PANEL} w-full p-5 gap-4'):
        with ui.row().classes('gap-3 items-end flex-wrap'):
            choice=ui.select(opts,value=party_id if party_id in opts else None,
                label='Pelanggan / pemasok',with_input=True).props('outlined').classes('w-72')
            begin=ui.input('Dari',value=start.isoformat() if start else '').props('outlined dense type=date').classes('w-44')
            until=ui.input('Sampai',value=end.isoformat()).props('outlined dense type=date').classes('w-44')
            def go():
                target=f'/subsidiary?party={choice.value or ""}&to={until.value}'
                if begin.value: target+=f'&from={begin.value}'
                ui.navigate.to(target)
            ui.button('Lihat',icon='search',on_click=go).props('no-caps')
        if party_id in opts:
            party=Party.objects.get(pk=party_id)
            data=subsidiary(party,start,end)
            with ui.grid(columns='repeat(auto-fit, minmax(215px, 1fr))').classes('w-full gap-3'):
                metric('Saldo Pembantu Awal',rupiah(data['opening']),'history')
                metric('Saldo Pembantu Akhir',rupiah(data['closing']),'account_balance_wallet','sky')
            datatable([('tanggal','Tanggal'),('bukti','Bukti'),('ket','Keterangan'),
                       ('debet','Debet',True),('kredit','Kredit',True),('saldo','Saldo',True)],
                [{'_key':i,'tanggal':x['date'].isoformat(),'bukti':x['reference'],
                  'ket':x['description'],'debet':rupiah(x['debit']),
                  'kredit':rupiah(x['credit']),'saldo':rupiah(x['balance'])}
                 for i,x in enumerate(data['records'])])
        else:
            ui.label('Belum ada relasi terpilih. Tambahkan relasi lewat menu Kode jika diperlukan.').classes(SUB)


@ui.page('/trial-balance')
def trial_page(request: Request):
    if not guard(): return
    end=query_date(request)
    rows=report_balances(end)
    debit=sum((r['debit'] for r in rows), ZERO)
    credit=sum((r['credit'] for r in rows), ZERO)
    shell('Neraca Saldo','/trial-balance','Keseimbangan saldo seluruh akun.')
    period_bar('/trial-balance',end)
    with ui.grid(columns='repeat(auto-fit, minmax(215px, 1fr))').classes('w-full gap-3'):
        metric('Total Debet',rupiah(debit),'arrow_downward')
        metric('Total Kredit',rupiah(credit),'arrow_upward','sky')
        metric('Selisih',rupiah(debit-credit),'fact_check','violet',
               'Idealnya bernilai nol')
    with ui.card().classes(f'{PANEL} w-full p-5'):
        datatable([('kode','Kode'),('nama','Nama Akun'),('kategori','Kategori'),
                   ('debet','Debet',True),('kredit','Kredit',True)],
                  [{'_key':r['account'].pk,'kode':r['account'].code,
                    'nama':r['account'].name,'kategori':r['account'].get_category_display(),
                    'debet':rupiah(r['debit']),'kredit':rupiah(r['credit'])} for r in rows])


@ui.page('/worksheet')
def worksheet_page(request: Request):
    if not guard(): return
    end=query_date(request)
    sheet=worksheet(end)
    shell('Neraca Lajur','/worksheet', 'Sepuluh kolom: saldo, penyesuaian, laporan laba rugi, dan neraca.')
    period_bar('/worksheet',end)
    with ui.grid(columns='repeat(auto-fit, minmax(215px, 1fr))').classes('w-full gap-3'):
        metric('Selisih Neraca Saldo',rupiah(sheet['check_trial']),'balance')
        metric('Selisih Disesuaikan',rupiah(sheet['check_adjusted']),'done_all','sky')
        metric('Laba Bersih',rupiah(sheet['profit']),'trending_up','violet')
    with ui.card().classes(f'{PANEL} w-full p-4'):
        keys=['trial_d','trial_c','adj_d','adj_c','adjusted_d','adjusted_c',
              'income_d','income_c','balance_d','balance_c']
        labels=['NS D','NS K','JP D','JP K','NS Adj D','NS Adj K','LR D','LR K','Neraca D','Neraca K']
        cols=[('kode','Kode'),('akun','Nama Akun')]+[(k,l,True) for k,l in zip(keys,labels)]
        data=[]
        for r in sheet['rows']:
            row={'_key':r['account'].pk,'kode':r['account'].code,'akun':r['account'].name}
            row.update({key:rupiah(r[key]) if r[key] else '-' for key in keys})
            data.append(row)
        datatable(cols,data,page_size=15)


def report_groups(kind, end):
    summary=period_totals(end)
    if kind=='income':
        order=[('REVENUE','Pendapatan Usaha'),('COGS','Harga Pokok Penjualan'),
               ('EXPENSE','Beban Operasional'),('OTHER_INCOME','Pendapatan Lain-lain'),
               ('OTHER_EXPENSE','Beban Lain-lain')]
        for cat,title in order:
            yield title,[{'account':r['account'],
                'amount':-r['net'] if cat in ('REVENUE','OTHER_INCOME') else r['net']}
                for r in summary['groups'].get(cat,[])]
    else:
        for cat,title in [('ASSET','Aset'),('LIABILITY','Kewajiban'),('EQUITY','Ekuitas')]:
            yield title,[{'account':r['account'],'amount':
                r['net'] if cat=='ASSET' else -r['net']}
                for r in summary['groups'].get(cat,[])]


@ui.page('/income')
def income_page(request: Request):
    if not guard(): return
    end=query_date(request)
    data=period_totals(end)
    shell('Laba Rugi','/income', 'Pendapatan, HPP, dan beban dihitung dari seluruh jurnal.')
    period_bar('/income',end)
    with ui.grid(columns='repeat(auto-fit, minmax(215px, 1fr))').classes('w-full gap-3'):
        metric('Pendapatan',rupiah(data['revenue']),'trending_up')
        metric('Total Beban + HPP',rupiah(data['costs']),'receipt_long','amber')
        metric('Laba / Rugi Bersih',rupiah(data['profit']),'insights','violet')
    with ui.card().classes(f'{PANEL} w-full p-5 gap-5'):
        for title,items in report_groups('income',end):
            with ui.column().classes('w-full gap-2'):
                section(title)
                datatable([('kode','Kode'),('nama','Akun'),('jumlah','Nominal',True)],
                          [{'_key':x['account'].pk,'kode':x['account'].code,
                            'nama':x['account'].name,'jumlah':rupiah(x['amount'])} for x in items],search=False)
                ui.label('Subtotal: '+rupiah(sum((x['amount'] for x in items),ZERO)))\
                    .classes('text-sm font-bold text-right w-full')


@ui.page('/balance')
def balance_page(request: Request):
    if not guard(): return
    end=query_date(request)
    data=period_totals(end)
    shell('Neraca','/balance','Posisi aset, kewajiban, ekuitas, dan laba berjalan.')
    period_bar('/balance',end)
    with ui.grid(columns='repeat(auto-fit, minmax(215px, 1fr))').classes('w-full gap-3'):
        metric('Aset',rupiah(data['assets']),'savings')
        metric('Kewajiban',rupiah(data['liabilities']),'credit_card','sky')
        metric('Ekuitas + Laba',rupiah(data['equity_with_profit']),'account_balance','violet')
        metric('Selisih Neraca',rupiah(data['difference']),'fact_check','amber')
    with ui.card().classes(f'{PANEL} w-full p-5 gap-5'):
        for title,items in report_groups('balance',end):
            section(title)
            datatable([('kode','Kode'),('nama','Akun'),('nominal','Saldo',True)],
                      [{'_key':x['account'].pk,'kode':x['account'].code,'nama':x['account'].name,
                        'nominal':rupiah(x['amount'])} for x in items],search=False)
            ui.label('Subtotal: '+rupiah(sum((x['amount'] for x in items),ZERO)))\
                .classes('text-sm font-bold text-right w-full')
        ui.separator()
        ui.label('Laba / Rugi Berjalan: '+rupiah(data['profit'])).classes('font-semibold text-emerald-800')
        ui.label('Kontrol SELISIH (HARUS 0): '+rupiah(data['difference'])).classes('font-extrabold text-lg')


# ------------------------------ FIFO ---------------------------------------
@ui.page('/inventory')
def inventory_page(request: Request):
    if not guard(): return
    end=query_date(request)
    product_id=request.query_params.get('product','')
    products={str(x.pk):str(x) for x in Product.objects.all()}
    shell('Inventory Card · FIFO','/inventory','Mutasi barang keluar/masuk dan perhitungan HPP perpetual.')
    with ui.card().classes(f'{PANEL} w-full p-5 gap-4'):
        with ui.row().classes('items-end justify-between gap-3 w-full flex-wrap'):
            product_choice=ui.select(products, value=product_id if product_id in products else None,
                                     label='Pilih komoditas',with_input=True).props('outlined').classes('w-72')
            until=ui.input('Sampai tanggal',value=end.isoformat()).props('outlined dense type=date').classes('w-44')
            ui.button('Lihat kartu',icon='search',on_click=lambda:ui.navigate.to(
                f'/inventory?product={product_choice.value or ""}&to={until.value}')).props('no-caps')
            action('Tambah mutasi','/inventory/new',icon='add',primary=True)
        if product_id in products:
            product=Product.objects.get(pk=product_id)
            card=stock_card(product,end=end)
            next_layer=(InventoryLayer.objects.filter(product=product,remaining_quantity__gt=0)
                        .select_related('movement').order_by('movement__date','movement__id','id').first())
            with ui.row().classes('w-full gap-3 flex-wrap'):
                metric('Sisa stok',f"{card['qty']} {product.unit}",'inventory')
                metric('Nilai stok',rupiah(card['value']),'account_balance_wallet','sky')
                metric('HPP lapisan terdekat',rupiah(next_layer.unit_cost) if next_layer else '-','price_check','amber')
            records=[]
            for item in card['records']:
                movement=item['movement']
                records.append({'_key':movement.pk,'tanggal':movement.date.isoformat(),
                                'bukti':movement.reference,'jenis':movement.get_kind_display(),
                                'keterangan':movement.description,
                                'masuk':str(item['in_qty'] or '-'),'keluar':str(item['out_qty'] or '-'),
                                'masuk_rp':rupiah(item['in_value']) if item['in_value'] is not None else '-',
                                'keluar_rp':rupiah(item['out_value']) if item['out_value'] is not None else '-',
                                'saldo_qty':str(item['qty']), 'saldo_nilai':rupiah(item['value'])})
            datatable([('tanggal','Tanggal'),('bukti','Bukti'),('jenis','Jenis'),('keterangan','Keterangan'),
                       ('masuk','Masuk'),('keluar','Keluar'),('masuk_rp','Nilai Masuk',True),
                       ('keluar_rp','Nilai Keluar',True),('saldo_qty','Sisa'),('saldo_nilai','Saldo Nilai',True)],records)
        else:
            ui.label('Pilih produk untuk melihat mutasi dan stok FIFO-nya.').classes(SUB)


@ui.page('/inventory/new')
def movement_new_page():
    if not guard(): return
    shell('Transaksi Persediaan','/inventory','Satu input membentuk mutasi stok dan jurnal perpetual otomatis.')
    frm=MovementForm()
    with ui.card().classes(f'{PANEL} w-full max-w-4xl p-6 gap-4'):
        with ui.grid(columns=2).classes('w-full gap-4'):
            widgets=form_widgets(frm)
        with ui.card().classes('w-full bg-emerald-50 rounded-2xl p-4 shadow-none'):
            ui.label('Logika lama dipertahankan').classes('font-bold text-emerald-900')
            ui.label('Barang masuk: Persediaan bertambah. Barang keluar: Penjualan & HPP FIFO diposting otomatis. Harga jual keluar mengikuti master produk.').classes('text-sm text-emerald-700')
        with ui.row().classes('w-full justify-end gap-2'):
            action('Batal','/inventory')
            def save():
                payload=collect_values(widgets)
                validated=MovementForm(payload)
                if not validated.is_valid():
                    notify_form_errors(validated)
                    return
                d=validated.cleaned_data
                try:
                    prefix=voucher_prefix([],movement_kind=d['kind'],settlement_code=d['settlement_account'].code)
                    ref=next_voucher_reference(prefix)
                    if d['kind']=='IN' and not d.get('unit_price'):
                        raise ValidationError('Harga beli/unit wajib diisi untuk stok masuk.')
                    price=d['product'].sale_price if d['kind']=='OUT' else d['unit_price']
                    if d['kind']=='OUT' and price<=ZERO:
                        raise ValidationError('Harga jual produk harus lebih besar dari nol.')
                    movement=create_stock_movement(product=d['product'],date_value=d['date'],
                        reference=ref,kind=d['kind'],quantity=d['quantity'],unit_price=price,
                        settlement_account=d['settlement_account'],description=d['description'],
                        party=d.get('party'),user=logged_user())
                    ui.notify('Mutasi FIFO dan jurnal otomatis tersimpan.',color='positive')
                    ui.navigate.to(f'/inventory?product={movement.product_id}')
                except (ValidationError,IntegrityError) as exc:
                    notify_error(exc)
            ui.button('Simpan Transaksi FIFO',on_click=save,icon='done_all')\
                .props('unelevated no-caps').classes('rounded-xl')


# -------------------- jurnal khusus dan penutup -----------------------------
def special_type(entry):
    lines=list(entry.lines.select_related('account').all())
    if not lines: return 'GENERAL'
    cash={'1110','1120','1130'}
    debit={x.account.code for x in lines if x.debit>ZERO}
    credit={x.account.code for x in lines if x.credit>ZERO}
    if debit & {'1140'} and credit & {'4110','4120'}: return 'SALES'
    if debit & {'1150','1160'} and credit & {'2110'}: return 'PURCHASES'
    if debit & cash: return 'CASH_RECEIPTS'
    if credit & cash: return 'CASH_DISBURSEMENTS'
    return 'GENERAL'


@ui.page('/special-journals')
def special_journals_page(request: Request):
    if not guard(): return
    start=query_date(request,'from',date(timezone.localdate().year,1,1))
    end=query_date(request)
    entries=list(JournalEntry.objects.filter(date__gte=start,date__lte=end)
        .exclude(kind__in=[JournalEntry.Kind.ADJUSTMENT,JournalEntry.Kind.CLOSING])
        .prefetch_related('lines__account').order_by('date','id'))
    groups={key:[] for key in ('SALES','PURCHASES','CASH_RECEIPTS','CASH_DISBURSEMENTS','GENERAL')}
    for e in entries: groups[special_type(e)].append(e)
    labels={'SALES':'Jurnal Penjualan Kredit','PURCHASES':'Jurnal Pembelian Kredit',
            'CASH_RECEIPTS':'Jurnal Penerimaan Kas','CASH_DISBURSEMENTS':'Jurnal Pengeluaran Kas',
            'GENERAL':'Jurnal Umum Lainnya'}
    shell('Jurnal Khusus','/special-journals','Klasifikasi jurnal berdasarkan akun yang diposting.')
    period_bar('/special-journals',end,start)
    for kind,records in groups.items():
        with ui.card().classes(f'{PANEL} w-full p-5'):
            section(labels[kind], f'{len(records)} dokumen jurnal')
            data=[]
            for entry in records:
                for line in entry.lines.all():
                    data.append({'_key':line.pk,'tanggal':entry.date.isoformat(),
                        'bukti':entry.reference,'keterangan':entry.description[:75],
                        'debet_akun':str(line.account) if line.debit else '-',
                        'debet':rupiah(line.debit) if line.debit else '-',
                        'kredit_akun':str(line.account) if line.credit else '-',
                        'kredit':rupiah(line.credit) if line.credit else '-'})
            datatable([('tanggal','Tanggal'),('bukti','Bukti'),('keterangan','Keterangan'),
                       ('debet_akun','Akun Debet'),('debet','Debet',True),
                       ('kredit_akun','Akun Kredit'),('kredit','Kredit',True)], data,search=False)


def closing_preview(start,end):
    nominal=Account.objects.filter(is_header=False,is_active=True,
        category__in=['REVENUE','COGS','EXPENSE','OTHER_INCOME','OTHER_EXPENSE']).order_by('code')
    totals={r['account_id']:(r['d'] or ZERO,r['c'] or ZERO)
            for r in JournalLine.objects.filter(entry__date__gte=start,entry__date__lte=end)
            .values('account_id').annotate(d=Sum('debit'),c=Sum('credit'))}
    rows=[]
    period_net=ZERO
    for acct in nominal:
        d,c=totals.get(acct.pk,(ZERO,ZERO))
        net=d-c
        if net:
            rows.append({'account':acct,'debit':d,'credit':c,
                         'closing_debit':max(-net,ZERO),'closing_credit':max(net,ZERO)})
            period_net+=net
    return rows,-period_net


@ui.page('/closing-journal')
def closing_page(request: Request):
    if not guard(): return
    today=timezone.localdate()
    start=query_date(request,'from',date(today.year,1,1))
    end=query_date(request)
    rows,profit=closing_preview(start,end)
    ref=f'TUTUP-{end:%Y%m%d}'
    exists=JournalEntry.objects.filter(reference=ref).exists()
    shell('Jurnal Penutup','/closing-journal',
          'Penutupan saldo nominal ke Ikhtisar Laba Rugi dan akun 3110.')
    period_bar('/closing-journal',end,start)
    with ui.grid(columns='repeat(auto-fit, minmax(215px, 1fr))').classes('w-full gap-3'):
        metric('Hasil Periode',rupiah(profit),'insights')
        metric('Akun Nominal Aktif',len(rows),'summarize','sky')
    with ui.card().classes(f'{PANEL} w-full p-5 gap-4'):
        section('Pratinjau saldo nominal',f'Periode {start} s.d. {end}')
        datatable([('kode','Kode'),('nama','Akun'),('debet','Debet',True),('kredit','Kredit',True),
                   ('tutup_d','Penutup Debet',True),('tutup_k','Penutup Kredit',True)],
                  [{'_key':r['account'].pk,'kode':r['account'].code,'nama':r['account'].name,
                    'debet':rupiah(r['debit']),'kredit':rupiah(r['credit']),
                    'tutup_d':rupiah(r['closing_debit']),'tutup_k':rupiah(r['closing_credit'])}
                   for r in rows],search=False)
        if exists:
            ui.label('Jurnal penutup untuk tanggal ini sudah ada. Tidak dibuat ulang.').classes('text-amber-700 font-semibold')
        elif not rows:
            ui.label('Belum ada transaksi nominal untuk periode ini.').classes(SUB)
        else:
            def confirm():
                with ui.dialog() as dlg, ui.card().classes('w-full max-w-lg p-5 gap-3 rounded-2xl'):
                    ui.label('Konfirmasi tutup buku').classes('text-xl font-bold')
                    ui.label('Akun nominal akan ditutup. Tindakan ini membuat jurnal akuntansi baru.').classes(SUB)
                    with ui.row().classes('w-full justify-end'):
                        ui.button('Batal',on_click=dlg.close).props('flat no-caps')
                        def post():
                            try:
                                if start>end: raise ValidationError('Tanggal awal melewati tanggal akhir.')
                                if JournalEntry.objects.filter(reference=ref).exists():
                                    raise ValidationError('Jurnal penutup periode ini sudah ada.')
                                summary, _=Account.objects.get_or_create(code='3900',defaults={
                                    'name':'Ikhtisar Laba Rugi','category':'EQUITY','normal_balance':'C',
                                    'opening_balance':ZERO,'is_active':True,'is_header':False})
                                retained=Account.objects.filter(code='3110',is_header=False,is_active=True).first()
                                if retained is None: raise ValidationError('Akun 3110 Retained Earnings belum tersedia.')
                                net_income_summary=ZERO
                                closing_lines=[]
                                for r in rows:
                                    debit,credit=r['debit'],r['credit']
                                    net=debit-credit
                                    if net>ZERO:
                                        closing_lines.append((r['account'],ZERO,net))
                                        net_income_summary-=net
                                    elif net<ZERO:
                                        closing_lines.append((r['account'],-net,ZERO))
                                        net_income_summary+=-net
                                if net_income_summary>ZERO:
                                    closing_lines.extend([(summary,ZERO,net_income_summary),
                                                          (summary,net_income_summary,ZERO),
                                                          (retained,ZERO,net_income_summary)])
                                elif net_income_summary<ZERO:
                                    loss=-net_income_summary
                                    closing_lines.extend([(summary,loss,ZERO),
                                                          (summary,ZERO,loss),
                                                          (retained,loss,ZERO)])
                                with transaction.atomic():
                                    entry=JournalEntry.objects.create(date=end,reference=ref,
                                        description=f'Jurnal penutup periode {start:%d-%m-%Y} s.d. {end:%d-%m-%Y}',
                                        kind=JournalEntry.Kind.CLOSING,created_by=logged_user())
                                    for acct,d,c in closing_lines:
                                        JournalLine.objects.create(entry=entry,account=acct,
                                            description='Penutupan saldo akun nominal',debit=d,credit=c)
                                ui.notify('Jurnal penutup berhasil dibuat.',color='positive')
                                ui.navigate.to('/closing-journal')
                            except (ValidationError,IntegrityError) as exc:
                                notify_error(exc)
                        ui.button('Ya, posting penutup',on_click=post,icon='lock').props('unelevated no-caps')
                dlg.open()
            ui.button('Buat Jurnal Penutup',icon='lock_clock',on_click=confirm)\
                .props('unelevated no-caps').classes('rounded-xl')


# -------------------- local app entrypoint ----------------------------------
def session_secret():
    from django.conf import settings
    supplied = os.getenv('NICEGUI_STORAGE_SECRET')
    if supplied:
        return supplied
    secret_path = ROOT / '.nicegui_secret'
    if secret_path.exists():
        return secret_path.read_text(encoding='utf-8').strip()
    secret_path.write_text(secrets.token_urlsafe(48), encoding='utf-8')
    try:
        secret_path.chmod(0o600)
    except OSError:
        pass
    return secret_path.read_text(encoding='utf-8').strip()


if __name__ in {'__main__','__mp_main__'}:
    # Set NICEGUI_STORAGE_SECRET in the environment for a stable private session secret.
    ui.run(title='Kebun Marjuki | Finance & Inventory', port=int(os.getenv('PORT','8080')),
           host=os.getenv('HOST','0.0.0.0'), reload=False, show=False,
           storage_secret=session_secret())
