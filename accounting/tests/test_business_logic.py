"""Backend regression tests for the unchanged Django accounting engine.

Legacy Django-template tests retained under legacy_original_django_view_tests.py
and intentionally not discovered: the HTTP/UI layer is now NiceGUI.
"""
from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from accounting.models import Account, Party, Product, JournalEntry, JournalLine, BusinessProfile
from accounting.services import period_totals, report_balances, stock_card, create_stock_movement, create_opening_stock
from accounting.exports import build_linked_workbook


class CoreAccountingTests(TestCase):
    def setUp(self):
        self.cash = Account.objects.create(code='1120',name='Kas Tunai',category='ASSET',normal_balance='D')
        self.inventory = Account.objects.create(code='1150',name='Persediaan',category='ASSET',normal_balance='D')
        self.sales = Account.objects.create(code='4110',name='Penjualan',category='REVENUE',normal_balance='C')
        self.cogs = Account.objects.create(code='5110',name='HPP',category='COGS',normal_balance='D')
        self.capital = Account.objects.create(code='3100',name='Modal',category='EQUITY',normal_balance='C')
        BusinessProfile.current()

    def test_double_entry_and_report_balancing(self):
        entry=JournalEntry.objects.create(date=date(2026,11,11),reference='TEST-01',description='Setoran modal')
        JournalLine.objects.create(entry=entry,account=self.cash,debit=Decimal('5000000'),credit=Decimal('0'))
        JournalLine.objects.create(entry=entry,account=self.capital,debit=Decimal('0'),credit=Decimal('5000000'))
        totals=period_totals(date(2026,11,11))
        self.assertEqual(totals['assets'], Decimal('5000000'))
        self.assertEqual(totals['equity'], Decimal('5000000'))
        self.assertEqual(totals['difference'], Decimal('0'))

    def test_opening_stock_layer(self):
        product=Product.objects.create(code='P01',name='Beras',unit='kg',sale_price=Decimal('30000'))
        movement=create_opening_stock(product,Decimal('10'),Decimal('20000'),date(2026,11,11))
        card=stock_card(product)
        self.assertEqual(card['qty'], Decimal('10'))
        self.assertEqual(card['value'], Decimal('200000'))

    def test_export_has_all_linked_sheets(self):
        workbook=build_linked_workbook(date(2026,11,11))
        self.assertIn('JURNAL UMUM',workbook.sheetnames)
        self.assertIn('BUKU BESAR',workbook.sheetnames)
        self.assertIn('INVENTORY CARD',workbook.sheetnames)
        self.assertIn('NERACA',workbook.sheetnames)
        self.assertTrue(any(c.data_type=='f' for row in workbook['NERACA'].iter_rows() for c in row))
