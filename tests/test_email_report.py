import unittest
from pathlib import Path
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from app.services import email_report


class EmailReportTests(unittest.TestCase):
    def test_png_handles_empty_and_mixed_currency(self):
        route = SimpleNamespace(departure_city="CTU", arrival_city="MIL",
                                departure_date=date(2026, 10, 1), return_date=date(2026, 10, 8))
        rows = [SimpleNamespace(started_at=datetime(2026, 9, 10), currency=c, price=p)
                for c, p in [("CNY", 4500), ("USD", 650)]]
        for data in ([], rows):
            result = email_report.render_chart(route, data)
            self.assertTrue(result.startswith(b"\x89PNG\r\n\x1a\n"))
        with open('/tmp/fly-anywhere-email-preview.png', 'wb') as out:
            out.write(result)

    def test_images_are_inline_without_download_attachments(self):
        route = SimpleNamespace(id=1, departure_city="CTU", arrival_city="YVR",
                                departure_date=date(2026, 10, 1), return_date=date(2026, 10, 8))
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        with patch.object(email_report, 'price_history', return_value=[]), \
             patch.object(email_report, 'render_chart', return_value=b'png'), \
             patch.object(email_report, 'exchange_history', return_value=[]), \
             patch.object(email_report, 'render_exchange_chart', return_value=b'png'):
            message = email_report.build_report(db, [route])
        images = [p for p in message.walk() if p.get_content_type() == 'image/png']
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0].get_content_disposition(), 'inline')
        self.assertIsNone(images[0].get_filename())
        self.assertFalse(any(p.get_content_disposition() == 'attachment' for p in message.walk()))
        html = message.get_body(preferencelist=('html',)).get_content()
        self.assertIn('cid:' + images[0]['Content-ID'][1:-1], html)
        self.assertIn('成都双流', html)
        self.assertIn('人民币 / 日元汇率', html)
        self.assertIn('暂无汇率记录', html)
        for image in images:
            self.assertIn('cid:' + image['Content-ID'][1:-1], html)

    def test_exchange_png_empty_single_and_multiple(self):
        rows = [SimpleNamespace(rate_date=date(2026, 9, day), rate=20 + day / 100)
                for day in (9, 10, 11)]
        for points in ([], rows[:1], rows):
            png = email_report.render_exchange_chart(points)
            self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        Path('/tmp/fly-anywhere-fx-email-preview.png').write_bytes(png)

    def test_failed_fetch_reports_saved_rate_and_inverse(self):
        from decimal import Decimal
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            rate=Decimal('20'), rate_date=date(2026, 9, 10), fetched_at=datetime(2026, 9, 11))
        with patch.object(email_report, 'exchange_history', return_value=[]), \
             patch.object(email_report, 'render_exchange_chart', return_value=b'png'):
            message = email_report.build_report(db, [], exchange_status=False)
        for body in ('plain', 'html'):
            content = message.get_body(preferencelist=(body,)).get_content()
            self.assertIn('获取失败', content)
            self.assertIn('100 日元 = 5.0000 人民币', content)
            self.assertIn('2026-09-10', content)

    def test_missing_credentials_does_not_connect(self):
        with patch.object(email_report.settings, 'EMAIL_ENABLED', True), \
             patch.object(email_report.settings, 'SMTP_PASSWORD', ''), \
             patch.object(email_report.smtplib, 'SMTP_SSL') as smtp:
            self.assertFalse(email_report.send_price_report(MagicMock(), []))
            smtp.assert_not_called()

    def test_tls_delivery(self):
        config = SimpleNamespace(EMAIL_ENABLED=True, EMAIL_TO='test@example.com',
                                 SMTP_HOST='smtp.example.com', SMTP_USERNAME='sender',
                                 SMTP_PASSWORD='test-secret', SMTP_PORT=465, SMTP_SSL=True)
        with patch.object(email_report, 'settings', config), \
             patch.object(email_report, 'build_report', return_value='message'), \
             patch.object(email_report.smtplib, 'SMTP_SSL') as smtp:
            self.assertTrue(email_report.send_price_report(MagicMock(), []))
            smtp.return_value.__enter__.return_value.send_message.assert_called_once_with('message')


if __name__ == '__main__':
    unittest.main()
