import unittest
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
