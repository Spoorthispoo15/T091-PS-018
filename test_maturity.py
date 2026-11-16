"""
Unit tests for Maturity Processing, Holiday Rollover, and Premature Withdrawal.
"""

import unittest
import datetime
from src.customer import CustomerManager
from src.rate_card import RateCardManager
from src.fd_booking import FDBookingService
from src.maturity_process import MaturityService


class TestMaturityProcess(unittest.TestCase):

    def setUp(self):
        self.customer_mgr = CustomerManager()
        self.customer_mgr.load_customers("data/customers.csv")
        self.rate_card_mgr = RateCardManager()
        self.rate_card_mgr.load_rate_cards("data/rate_cards.csv")
        self.booking_service = FDBookingService(self.rate_card_mgr, self.customer_mgr)
        self.maturity_service = MaturityService(self.customer_mgr, self.rate_card_mgr, self.booking_service)
        self.maturity_service.load_holidays("data/holidays.csv")

    def test_premature_withdrawal_day_7_vs_8_ec03(self):
        # Book on 2025-01-06
        fd23 = self.booking_service.book_fd(
            fd_id="TEST-0023",
            customer_id="CUST-003",
            amount=80000.0,
            tenure_value=12,
            tenure_unit="M",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2025, 1, 6)
        )
        # Day 7 withdrawal: 2025-01-13 (7 days) -> principal only, 0 interest, 0 penalty
        ok, msg, p, g_int, tds, net = self.maturity_service.process_premature_withdrawal(
            "TEST-0023", datetime.date(2025, 1, 13), "FULL"
        )
        self.assertTrue(ok)
        self.assertEqual(p, 80000.0)
        self.assertEqual(g_int, 0.0)
        self.assertEqual(net, 80000.0)
        self.assertEqual(fd23.status, "CLOSED")

        # Day 8 withdrawal on fresh FD booked 2025-01-06
        fd24 = self.booking_service.book_fd(
            fd_id="TEST-0024",
            customer_id="CUST-003",
            amount=80000.0,
            tenure_value=12,
            tenure_unit="M",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2025, 1, 6)
        )
        # Day 8 withdrawal: 2025-01-14 (8 days) -> re-priced at 7-45D rate (3.00%) minus 1% penalty = 2.00%
        # 80000 * 0.02 * 8 / 365 = 35.07
        ok2, msg2, p2, g_int2, tds2, net2 = self.maturity_service.process_premature_withdrawal(
            "TEST-0024", datetime.date(2025, 1, 14), "FULL"
        )
        self.assertTrue(ok2)
        self.assertEqual(p2, 80000.0)
        self.assertEqual(g_int2, 35.07)
        self.assertEqual(net2, 80035.07)
        self.assertEqual(fd24.status, "CLOSED")

    def test_partial_withdrawal_constraints_ec04(self):
        # FD-0021 of 25,000
        fd21 = self.booking_service.book_fd(
            fd_id="TEST-0021",
            customer_id="CUST-004",
            amount=25000.0,
            tenure_value=24,
            tenure_unit="M",
            fd_type="CUMULATIVE",
            instruction="RENEW_PRINCIPAL",
            booking_date=datetime.date(2024, 11, 4)
        )
        # Withdrawal of 20,000 leaves exactly 5,000 -> allowed
        ok, msg, p, g_int, tds, net = self.maturity_service.process_premature_withdrawal(
            "TEST-0021", datetime.date(2025, 4, 10), "20000.00"
        )
        self.assertTrue(ok)
        self.assertEqual(p, 20000.0)
        self.assertEqual(fd21.principal, 5000.0)
        self.assertEqual(fd21.status, "ACTIVE")

        # FD-0022 of 25,000
        fd22 = self.booking_service.book_fd(
            fd_id="TEST-0022",
            customer_id="CUST-004",
            amount=25000.0,
            tenure_value=24,
            tenure_unit="M",
            fd_type="CUMULATIVE",
            instruction="RENEW_PRINCIPAL",
            booking_date=datetime.date(2024, 11, 4)
        )
        # Withdrawal of 21,000 leaves 4,000 (< 5,000) -> rejected
        ok_bad1, msg_bad1, _, _, _, _ = self.maturity_service.process_premature_withdrawal(
            "TEST-0022", datetime.date(2025, 4, 10), "21000.00"
        )
        self.assertFalse(ok_bad1)
        self.assertEqual(fd22.principal, 25000.0)

        # Withdrawal of 1,500 is not a multiple of 1,000 -> rejected
        ok_bad2, msg_bad2, _, _, _, _ = self.maturity_service.process_premature_withdrawal(
            "TEST-0022", datetime.date(2025, 4, 11), "1500.00"
        )
        self.assertFalse(ok_bad2)
        self.assertEqual(fd22.principal, 25000.0)

    def test_holiday_weekend_maturity_rollover_ec06(self):
        # FD-0013 matures 2025-08-15 (Friday, Independence Day)
        fd13 = self.booking_service.book_fd(
            fd_id="TEST-0013",
            customer_id="CUST-006",
            amount=200000.0,
            tenure_value=15,
            tenure_unit="M",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2024, 5, 15)
        )
        self.assertEqual(fd13.maturity_date, datetime.date(2025, 8, 15))

        eff_date, extra_days, extra_int = self.maturity_service.get_effective_maturity_details(fd13)
        # Next business day after Fri holiday + Sat/Sun is Monday 2025-08-18 (3 extra days)
        self.assertEqual(eff_date, datetime.date(2025, 8, 18))
        self.assertEqual(extra_days, 3)
        self.assertGreater(extra_int, 0.0)

    def test_lien_blocks_premature_withdrawal_ec07(self):
        fd16 = self.booking_service.book_fd(
            fd_id="TEST-0016",
            customer_id="CUST-007",
            amount=400000.0,
            tenure_value=24,
            tenure_unit="M",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2024, 7, 1)
        )
        # Place loan / lien
        fd16.lien = True
        fd16.loan_principal = 360000.0

        # Withdrawal attempt while lien is active -> rejected
        ok_blocked, _, _, _, _, _ = self.maturity_service.process_premature_withdrawal(
            "TEST-0016", datetime.date(2025, 2, 1), "FULL"
        )
        self.assertFalse(ok_blocked)
        self.assertEqual(fd16.status, "ACTIVE")

        # Repay loan / clear lien
        fd16.lien = False
        fd16.loan_principal = 0.0

        # Withdrawal allowed
        ok_allowed, _, p, _, _, _ = self.maturity_service.process_premature_withdrawal(
            "TEST-0016", datetime.date(2025, 3, 3), "FULL"
        )
        self.assertTrue(ok_allowed)
        self.assertEqual(p, 400000.0)
        self.assertEqual(fd16.status, "CLOSED")

    def test_withdrawal_on_closed_fd_rejected(self):
        fd = self.booking_service.book_fd(
            fd_id="TEST-CLOSED",
            customer_id="CUST-001",
            amount=50000.0,
            tenure_value=30,
            tenure_unit="D",
            fd_type="CUMULATIVE",
            instruction="PAYOUT",
            booking_date=datetime.date(2024, 1, 1)
        )
        fd.status = "CLOSED"
        ok, msg, _, _, _, _ = self.maturity_service.process_premature_withdrawal(
            "TEST-CLOSED", datetime.date(2024, 1, 15), "FULL"
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
