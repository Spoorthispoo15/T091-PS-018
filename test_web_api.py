"""
Comprehensive Web API Test Suite for Fixed Deposit Banking Engine.
Tests all Flask endpoints and verifies seamless integration with Python business logic.
"""

import unittest
import json
import datetime
from app import app, bank_app


class TestWebAPI(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        # Reset engine state before each test
        bank_app.load_initial_data()

    def test_index_page(self):
        """Verify dashboard HTML page loads successfully."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"APEX TRUST BANK", response.data)
        self.assertIn(b"FD ENGINE PS-018", response.data)

    def test_dashboard_api(self):
        """Verify dashboard statistics and recent events."""
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data["success"])
        self.assertGreater(data["total_deposits"], 20)
        self.assertGreater(data["total_active_principal"], 0)
        self.assertGreater(data["total_interest_paid_credited"], 0)
        self.assertTrue(isinstance(data["recent_events"], list))

    def test_customers_api(self):
        """Verify listing customers with calculated attributes."""
        response = self.client.get("/api/customers")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data["success"])
        customers = {c["customer_id"]: c for c in data["customers"]}
        self.assertIn("CUST-001", customers)
        # CUST-001 DOB is 1958-02-11 -> Senior citizen
        self.assertTrue(customers["CUST-001"]["is_senior"])
        # CUST-009 missing PAN -> TDS 20%
        self.assertEqual(customers["CUST-009"]["tds_rate"], 20.0)
        # CUST-008 has Form 15H -> TDS 0%
        self.assertEqual(customers["CUST-008"]["tds_rate"], 0.0)

    def test_create_customer_validation(self):
        """Verify creating a customer with validation."""
        # Missing required fields
        res_bad = self.client.post("/api/customers", json={"customer_id": ""})
        self.assertEqual(res_bad.status_code, 400)

        # Valid customer
        res_ok = self.client.post("/api/customers", json={
            "customer_id": "TEST-CUST-99",
            "customer_name": "Rohan Sharma",
            "date_of_birth": "1960-01-01",
            "pan": "ABCDE1234F",
            "form_15g_15h": False,
            "savings_account_no": "SB9998887771"
        })
        self.assertEqual(res_ok.status_code, 200)
        data = json.loads(res_ok.data)
        self.assertTrue(data["success"])

        # Duplicate ID should be rejected
        res_dup = self.client.post("/api/customers", json={
            "customer_id": "TEST-CUST-99",
            "customer_name": "Duplicate",
            "date_of_birth": "1990-01-01",
            "savings_account_no": "SB1111111111"
        })
        self.assertEqual(res_dup.status_code, 400)

    def test_rate_preview_api(self):
        """Verify dynamic rate card preview and senior add-on rules."""
        # CUST-001 (Senior) for 180 days -> Senior add-on +0.50% (5.75% + 0.50% = 6.25%)
        res = self.client.post("/api/fd/preview-rate", json={
            "customer_id": "CUST-001",
            "amount": 300000,
            "tenure_value": 180,
            "tenure_unit": "D",
            "fd_type": "CUMULATIVE",
            "booking_date": "2023-06-14"
        })
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data["success"])
        self.assertEqual(data["card_id"], "RC-2023")
        self.assertEqual(data["effective_rate"], 6.25)
        self.assertEqual(data["senior_addon"], 0.50)
        self.assertEqual(data["tenure_days"], 180)

        # 179 days does NOT get senior add-on
        res179 = self.client.post("/api/fd/preview-rate", json={
            "customer_id": "CUST-001",
            "amount": 300000,
            "tenure_value": 179,
            "tenure_unit": "D",
            "fd_type": "CUMULATIVE",
            "booking_date": "2023-06-15"
        })
        data179 = json.loads(res179.data)
        self.assertEqual(data179["effective_rate"], 4.50)
        self.assertEqual(data179["senior_addon"], 0.0)

    def test_booking_validation_rules(self):
        """Verify booking validations (min 5000, 7-3650 days)."""
        # Less than 5000 rejected
        res_amt = self.client.post("/api/fd/book", json={
            "customer_id": "CUST-001",
            "amount": 4999,
            "tenure_value": 30,
            "tenure_unit": "D",
            "fd_type": "CUMULATIVE",
            "booking_date": "2025-01-01"
        })
        self.assertEqual(res_amt.status_code, 400)

        # Tenure < 7 days rejected
        res_tenure_low = self.client.post("/api/fd/book", json={
            "customer_id": "CUST-001",
            "amount": 10000,
            "tenure_value": 6,
            "tenure_unit": "D",
            "fd_type": "CUMULATIVE",
            "booking_date": "2025-01-01"
        })
        self.assertEqual(res_tenure_low.status_code, 400)

        # Tenure > 3650 days rejected
        res_tenure_high = self.client.post("/api/fd/book", json={
            "customer_id": "CUST-001",
            "amount": 10000,
            "tenure_value": 3651,
            "tenure_unit": "D",
            "fd_type": "CUMULATIVE",
            "booking_date": "2025-01-01"
        })
        self.assertEqual(res_tenure_high.status_code, 400)

    def test_successful_booking_and_lifecycle(self):
        """Verify successful booking, loan, loan repayment, and premature withdrawal."""
        # Book a new FD
        res_book = self.client.post("/api/fd/book", json={
            "fd_id": "TEST-WEB-01",
            "customer_id": "CUST-002",
            "amount": 100000.0,
            "tenure_value": 12,
            "tenure_unit": "M",
            "fd_type": "CUMULATIVE",
            "maturity_instruction": "PAYOUT",
            "booking_date": "2025-01-01"
        })
        self.assertEqual(res_book.status_code, 200)
        book_data = json.loads(res_book.data)
        self.assertTrue(book_data["success"])
        self.assertEqual(book_data["deposit"]["status"], "ACTIVE")

        # Sanction loan up to 90%
        res_loan = self.client.post("/api/fd/loan", json={
            "fd_id": "TEST-WEB-01",
            "amount": "MAX",
            "date": "2025-01-10"
        })
        self.assertEqual(res_loan.status_code, 200)
        loan_data = json.loads(res_loan.data)
        self.assertEqual(loan_data["loan_principal"], 90000.0)
        self.assertTrue(loan_data["lien"])

        # Premature withdrawal blocked while lien is active
        res_withdraw_blocked = self.client.post("/api/fd/withdraw", json={
            "fd_id": "TEST-WEB-01",
            "date": "2025-01-15",
            "amount": "FULL"
        })
        self.assertEqual(res_withdraw_blocked.status_code, 400)

        # Repay loan
        res_repay = self.client.post("/api/fd/loan-repay", json={
            "fd_id": "TEST-WEB-01",
            "amount": "FULL",
            "date": "2025-01-20"
        })
        self.assertEqual(res_repay.status_code, 200)
        repay_data = json.loads(res_repay.data)
        self.assertEqual(repay_data["remaining_loan"], 0.0)
        self.assertFalse(repay_data["lien_active"])

        # Now premature withdrawal succeeds
        res_withdraw_ok = self.client.post("/api/fd/withdraw", json={
            "fd_id": "TEST-WEB-01",
            "date": "2025-01-25",
            "amount": "FULL"
        })
        self.assertEqual(res_withdraw_ok.status_code, 200)
        withdraw_data = json.loads(res_withdraw_ok.data)
        self.assertTrue(withdraw_data["success"])
        self.assertEqual(withdraw_data["details"]["status_after"], "CLOSED")

    def test_backdating_api(self):
        """Verify backdating up to 3 days."""
        # Book FD on 2025-03-19
        self.client.post("/api/fd/book", json={
            "fd_id": "TEST-BACKDATE",
            "customer_id": "CUST-003",
            "amount": 50000.0,
            "tenure_value": 30,
            "tenure_unit": "D",
            "fd_type": "CUMULATIVE",
            "booking_date": "2025-03-19"
        })

        # Backdate by 3 days (to 2025-03-16) -> Allowed
        res_3d = self.client.post("/api/fd/backdate", json={
            "fd_id": "TEST-BACKDATE",
            "value_date": "2025-03-16"
        })
        self.assertEqual(res_3d.status_code, 200)

        # Backdate by 4 days (to 2025-03-15) -> Rejected
        res_4d = self.client.post("/api/fd/backdate", json={
            "fd_id": "TEST-BACKDATE",
            "value_date": "2025-03-15"
        })
        self.assertEqual(res_4d.status_code, 400)

    def test_interest_calculator_api(self):
        """Verify standalone calculator formulas."""
        res = self.client.post("/api/calculate-interest", json={
            "principal": 150000.0,
            "rate_pct": 7.30,
            "tenure_value": 18,
            "tenure_unit": "M",
            "start_date": "2024-01-01"
        })
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data["success"])
        # Monthly payout formula: 150000 * 0.073 * 0.9975 / 12 = 910.22
        self.assertEqual(data["monthly_payout"], 910.22)
        self.assertGreater(data["cumulative_maturity_value"], 150000.0)

    def test_reports_api(self):
        """Verify reports retrieval and download."""
        for report in ["advices", "events", "interest-certificates", "tds-statements"]:
            res = self.client.get(f"/api/reports/{report}")
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertTrue(data["success"])

        # Test download CSV
        res_dl = self.client.get("/api/reports/download/fd_advices.csv")
        self.assertEqual(res_dl.status_code, 200)
        self.assertEqual(res_dl.mimetype, "text/csv")


if __name__ == "__main__":
    unittest.main()
