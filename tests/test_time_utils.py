import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from chiro_outreach import form_submitter, gmail_client
from chiro_outreach.time_utils import parse_iso_datetime


class OutreachTimeTests(unittest.TestCase):
    def test_existing_imports_use_one_parser(self):
        self.assertIs(gmail_client.parse_iso_datetime, parse_iso_datetime)
        self.assertIs(form_submitter.parse_iso_datetime, parse_iso_datetime)

    def test_legacy_naive_utc_and_offset_timestamps(self):
        expected = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        for value in ["2026-10-23T12:00:00", "2026-10-23T12:00:00Z", "2026-10-23T08:00:00-04:00"]:
            with self.subTest(value=value):
                self.assertEqual(parse_iso_datetime(value), expected)
        for value in ["", "bad"]:
            self.assertIsNone(parse_iso_datetime(value))

    def test_daily_channel_caps_keep_their_existing_event_scopes(self):
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        old = recent - timedelta(days=2)
        rows = [
            {"event_type": event, "timestamp": recent.isoformat()}
            for event in ["sent", "demo_followup_sent", "form_submitted", "drafted"]
        ] + [
            {"event_type": "sent", "timestamp": old.isoformat()},
            {"event_type": "sent", "timestamp": "bad"},
        ]
        for module, count in [(gmail_client, gmail_client.sent_in_last_24_hours),
                              (form_submitter, form_submitter.outreach_events_in_last_24_hours)]:
            with patch.object(module, "read_rows", return_value=rows):
                self.assertEqual(count(), 2)


if __name__ == "__main__":
    unittest.main()
