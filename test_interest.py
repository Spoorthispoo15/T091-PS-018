"""
Unit tests for interest calculation module.
"""

import unittest
from src.interest_calculation import (
    calculate_monthly_interest,
    calculate_total_interest,
    calculate_broken_monthly_interest,
    calculate_quarterly_interest,
    calculate_broken_quarterly_interest,
    calculate_daily_interest,
    calculate_holiday_delay_interest,
    calculate_premature_penalty_rate,
)


class TestInterestCalculation(unittest.TestCase):

    def test_monthly_interest_valid(self):
        # 150,000 at 7.30% p.a.
        # 150000 * 0.073 * 0.9975 / 12 = 910.21875 -> 910.22
        interest = calculate_monthly_interest(150000.0, 7.30)
        self.assertEqual(interest, 910.22)

    def test_monthly_interest_large_deposit(self):
        # 5,000,000 at 7.00% p.a.
        # 5000000 * 0.07 * 0.9975 / 12 = 29093.75
        interest = calculate_monthly_interest(5000000.0, 7.00)
        self.assertEqual(interest, 29093.75)

    def test_monthly_interest_invalid_principal(self):
        with self.assertRaises(ValueError):
            calculate_monthly_interest(0.0, 6.5)
        with self.assertRaises(ValueError):
            calculate_monthly_interest(-5000.0, 6.5)

    def test_monthly_interest_invalid_rate(self):
        with self.assertRaises(ValueError):
            calculate_monthly_interest(10000.0, -1.0)

    def test_total_interest(self):
        # 100,000 at 6.00% for 12 months
        total = calculate_total_interest(100000.0, 6.00, 12)
        expected = round(calculate_monthly_interest(100000.0, 6.00) * 12, 2)
        self.assertEqual(total, expected)

    def test_total_interest_invalid_months(self):
        with self.assertRaises(ValueError):
            calculate_total_interest(50000.0, 7.0, 0)
        with self.assertRaises(ValueError):
            calculate_total_interest(50000.0, 7.0, -5)

    def test_broken_monthly_interest(self):
        # 1 day out of 30 days in April
        # 150000 * 0.073 * 0.9975 / 12 * (1 / 30) = 30.34
        broken = calculate_broken_monthly_interest(150000.0, 7.30, 1, 30)
        self.assertEqual(broken, 30.34)

    def test_quarterly_interest_full(self):
        # 700,000 at 7.00% p.a.
        # 700000 * 0.07 / 4 = 12250.00
        q_int = calculate_quarterly_interest(700000.0, 7.00)
        self.assertEqual(q_int, 12250.00)

    def test_broken_quarterly_interest(self):
        # 54 active days out of 91 days in Q1
        # 50000 * 0.075 / 4 * (54 / 91) = 556.32
        broken_q = calculate_broken_quarterly_interest(50000.0, 7.50, 54, 91)
        self.assertEqual(broken_q, 556.32)

    def test_holiday_delay_savings_interest(self):
        # 200,000 maturity value delayed by 3 days at 3% savings rate
        # 200000 * 0.03 * 3 / 365 = 49.32
        extra = calculate_holiday_delay_interest(200000.0, 3, savings_rate=3.0)
        self.assertEqual(extra, 49.32)

    def test_premature_penalty_rate(self):
        # Applicable band rate 4.50% - 1.00% penalty = 3.50%
        penalty_rate = calculate_premature_penalty_rate(4.50, penalty_pct=1.0)
        self.assertEqual(penalty_rate, 3.50)

    def test_premature_penalty_rate_clamped(self):
        # Low rate clamped at 0%
        penalty_rate = calculate_premature_penalty_rate(0.50, penalty_pct=1.0)
        self.assertEqual(penalty_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
