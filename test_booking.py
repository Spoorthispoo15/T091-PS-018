"""
Unit tests for Fixed Deposit Booking and Validation.
"""

import unittest
import datetime
from src.customer import CustomerManager
from src.rate_card import RateCardManager
from src.fd_booking import FDBookingService, add_months


class TestFDBooking(unittest.TestCase):

    def setUp(self):
        self.customer_mgr = CustomerManager()
        self.customer_mgr.load_customers("data/customers.csv")
        self.rate_card_mgr = RateCardManager()
        self.rate_card_mgr.load_rate_cards("data/rate_cards.csv")
        self.service = FDBookingService(self.rate_card_mgr, self.customer_mgr)

    def test_senior_addon_threshold_ec01(self):
        # EC-01: CUST-001 (Senior):
        # FD-0004 for 180 days gets +0.50% senior addon (5.75% + 0.50% = 6.25%)
        fd_180 = self.service.book_fd(
            fd_id="TEST-0004",
            customer_id="CUST-001",
            amount=300000.0,
            tenure_value=180,
            tenure_unit="D",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2023, 6, 14)
        )
        self.assertEqual(fd_180.status, "ACTIVE")
        self.assertEqual(fd_180.tenure_days, 180)
        self.assertEqual(fd_180.rate_pct, 6.25)

        # FD-0005 for 179 days does NOT get senior addon (stays 4.50%)
        fd_179 = self.service.book_fd(
            fd_id="TEST-0005",
            customer_id="CUST-001",
            amount=300000.0,
            tenure_value=179,
            tenure_unit="D",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2023, 6, 15)
        )
        self.assertEqual(fd_179.status, "ACTIVE")
        self.assertEqual(fd_179.tenure_days, 179)
        self.assertEqual(fd_179.rate_pct, 4.50)

    def test_month_end_maturity_ec02(self):
        # EC-02: 31 Aug 2023 for 6 months -> 2024-02-29 (leap year)
        mat_leap = add_months(datetime.date(2023, 8, 31), 6)
        self.assertEqual(mat_leap, datetime.date(2024, 2, 29))

        # 31 Aug 2024 for 6 months -> 2025-02-28 (non-leap year)
        mat_non_leap = add_months(datetime.date(2024, 8, 31), 6)
        self.assertEqual(mat_non_leap, datetime.date(2025, 2, 28))

    def test_booking_minimum_amount_validation(self):
        # Rs 4,999 is rejected (minimum 5,000)
        fd = self.service.book_fd(
            fd_id="TEST-0030",
            customer_id="CUST-006",
            amount=4999.0,
            tenure_value=12,
            tenure_unit="M",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2025, 5, 6)
        )
        self.assertEqual(fd.status, "REJECTED")

    def test_booking_minimum_tenure_validation(self):
        # 6 days is rejected (minimum 7 days)
        fd = self.service.book_fd(
            fd_id="TEST-0031",
            customer_id="CUST-006",
            amount=50000.0,
            tenure_value=6,
            tenure_unit="D",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2025, 5, 6)
        )
        self.assertEqual(fd.status, "REJECTED")

    def test_booking_maximum_tenure_validation(self):
        # 3,651 days is rejected (maximum 10 years / 3,650 days)
        fd = self.service.book_fd(
            fd_id="TEST-0032",
            customer_id="CUST-002",
            amount=100000.0,
            tenure_value=3651,
            tenure_unit="D",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2025, 6, 9)
        )
        self.assertEqual(fd.status, "REJECTED")

    def test_backdating_valid_and_rejected(self):
        # Book FD on 2025-03-19
        fd1 = self.service.book_fd(
            fd_id="TEST-0028",
            customer_id="CUST-010",
            amount=600000.0,
            tenure_value=400,
            tenure_unit="D",
            fd_type="CUMULATIVE",
            instruction="RENEW_ALL",
            booking_date=datetime.date(2025, 3, 19)
        )
        # Backdate 3 days back (2025-03-16) -> allowed, rate card RC-2023 applies
        res = self.service.backdate_fd("TEST-0028", datetime.date(2025, 3, 16))
        self.assertTrue(res)
        self.assertEqual(fd1.value_date, datetime.date(2025, 3, 16))
        self.assertEqual(fd1.card_id, "RC-2023")

        # Book FD on 2025-03-21
        fd2 = self.service.book_fd(
            fd_id="TEST-0029",
            customer_id="CUST-010",
            amount=600000.0,
            tenure_value=400,
            tenure_unit="D",
            fd_type="CUMULATIVE",
            instruction="RENEW_ALL",
            booking_date=datetime.date(2025, 3, 21)
        )
        # Backdate 4 days back (2025-03-17) -> rejected!
        res4 = self.service.backdate_fd("TEST-0029", datetime.date(2025, 3, 17))
        self.assertFalse(res4)
        self.assertEqual(fd2.value_date, datetime.date(2025, 3, 21))

    def test_ge_2cr_band_matching(self):
        # 2 Crore deposit matches GE_2CR band
        fd = self.service.book_fd(
            fd_id="TEST-0014",
            customer_id="CUST-010",
            amount=20000000.0,
            tenure_value=12,
            tenure_unit="M",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2024, 6, 3)
        )
        self.assertEqual(fd.status, "ACTIVE")
        # In RC-2023: 1-2Y GE_2CR is 7.05%
        self.assertEqual(fd.rate_pct, 7.05)


if __name__ == "__main__":
    unittest.main()
