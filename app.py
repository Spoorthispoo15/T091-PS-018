"""
Flask Web Application for Fixed Deposit Booking, Renewal and Premature Withdrawal Engine.
Project: PS-018
Team: T091
"""

import os
import sys
import datetime
import calendar
import csv
from typing import Dict, Any, Optional
from flask import Flask, render_template, request, jsonify, send_file, Response

# Add current workspace directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.command_processor import CommandProcessor, FDEvent, TDSStatementRecord
from src.customer import Customer, CustomerManager, get_financial_year
from src.rate_card import RateCardManager
from src.fd_booking import (
    FixedDeposit,
    FDBookingService,
    add_months,
    project_cumulative_maturity_value,
    get_quarter_end,
    get_next_quarter_end,
    get_days_in_quarter,
)
from src.maturity_process import MaturityService
from src.interest_calculation import (
    calculate_monthly_interest,
    calculate_broken_monthly_interest,
    calculate_quarterly_interest,
    calculate_broken_quarterly_interest,
    calculate_daily_interest,
    calculate_holiday_delay_interest,
    calculate_premature_penalty_rate,
)

app = Flask(__name__)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

class BankingEngineApp:
    """Manages application state and coordinates between web API and Python business logic."""

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self.engine: CommandProcessor = CommandProcessor(data_dir=self.data_dir)
        self.load_initial_data()

    def load_initial_data(self):
        """Loads rate cards, holidays, customers, and executes the benchmark commands."""
        self.engine = CommandProcessor(data_dir=self.data_dir)
        commands_file = os.path.join(self.data_dir, "commands.txt")
        if os.path.exists(commands_file):
            self.engine.execute_command_file(commands_file)
            self.engine.generate_outputs(output_dir=".")
        else:
            # Fallback loading individual CSVs if commands.txt is missing
            self.engine.rate_card_mgr.load_rate_cards(os.path.join(self.data_dir, "rate_cards.csv"))
            self.engine.maturity_service.load_holidays(os.path.join(self.data_dir, "holidays.csv"))
            self.engine.customer_mgr.load_customers(os.path.join(self.data_dir, "customers.csv"))
            self.engine.current_sim_date = datetime.date.today()

    @property
    def current_date(self) -> datetime.date:
        return self.engine.current_sim_date or datetime.date.today()


# Initialize global engine
bank_app = BankingEngineApp()


# ==============================================================================
# Web Page Route
# ==============================================================================

@app.route("/")
def index():
    return render_template("index.html")


# ==============================================================================
# Dashboard API
# ==============================================================================

@app.route("/api/dashboard", methods=["GET"])
def get_dashboard_data():
    deposits = list(bank_app.engine.booking_service.deposits.values())
    customers = list(bank_app.engine.customer_mgr.customers.values())
    events = bank_app.engine.events
    curr_date = bank_app.current_date

    active_fds = [d for d in deposits if d.status == "ACTIVE"]
    matured_fds = [d for d in deposits if d.status == "MATURED"]
    renewed_fds = [d for d in deposits if d.status == "RENEWED"]
    closed_fds = [d for d in deposits if d.status == "CLOSED"]
    rejected_fds = [d for d in deposits if d.status == "REJECTED"]

    total_active_principal = sum(d.principal for d in active_fds)
    total_maturity_value = sum(d.maturity_value for d in active_fds)

    # Calculate overall interest and TDS across all customers
    total_interest = sum(sum(c.fy_interest.values()) for c in customers)
    total_tds = sum(sum(c.fy_tds.values()) for c in customers)

    # Recent 10 events
    recent_events = []
    for evt in reversed(events[-15:]):
        recent_events.append({
            "fd_id": evt.fd_id,
            "date": evt.date.strftime("%Y-%m-%d"),
            "event": evt.event,
            "amount": evt.amount,
            "tds": evt.tds,
            "net_amount": evt.net_amount,
            "principal_after": evt.principal_after,
            "note": evt.note,
        })

    return jsonify({
        "success": True,
        "current_date": curr_date.strftime("%Y-%m-%d"),
        "total_customers": len(customers),
        "total_deposits": len(deposits),
        "active_deposits_count": len(active_fds),
        "matured_deposits_count": len(matured_fds),
        "renewed_deposits_count": len(renewed_fds),
        "closed_deposits_count": len(closed_fds),
        "rejected_deposits_count": len(rejected_fds),
        "total_active_principal": round(total_active_principal, 2),
        "total_projected_maturity": round(total_maturity_value, 2),
        "total_interest_paid_credited": round(total_interest, 2),
        "total_tds_deducted": round(total_tds, 2),
        "recent_events": recent_events,
    })


# ==============================================================================
# Customer Management APIs
# ==============================================================================

@app.route("/api/customers", methods=["GET"])
def list_customers():
    curr_date = bank_app.current_date
    customers_data = []
    for c in bank_app.engine.customer_mgr.customers.values():
        is_senior = c.is_senior(curr_date)
        tds_rate = c.get_tds_rate()
        
        # Calculate totals across financial years
        tot_interest = round(sum(c.fy_interest.values()), 2)
        tot_tds = round(sum(c.fy_tds.values()), 2)

        # Count active FDs
        customer_fds = [
            fd for fd in bank_app.engine.booking_service.deposits.values()
            if fd.customer_id == c.customer_id and fd.status == "ACTIVE"
        ]

        customers_data.append({
            "customer_id": c.customer_id,
            "customer_name": c.customer_name,
            "date_of_birth": c.date_of_birth.strftime("%Y-%m-%d"),
            "is_senior": is_senior,
            "pan": c.pan or "MISSING",
            "has_pan": bool(c.pan and c.pan.strip()),
            "form_15g_15h": c.form_15g_15h,
            "tds_rate": tds_rate,
            "savings_account_no": c.savings_account_no,
            "active_fds_count": len(customer_fds),
            "total_interest": tot_interest,
            "total_tds": tot_tds,
            "fy_breakdown": {
                fy: {
                    "interest": c.fy_interest[fy],
                    "tds": c.fy_tds[fy],
                    "threshold_crossed": c.fy_threshold_crossed.get(fy, False),
                    "fd_count": len(c.fy_fds.get(fy, set())),
                }
                for fy in c.fy_interest
            }
        })

    # Sort by customer_id
    customers_data.sort(key=lambda x: x["customer_id"])
    return jsonify({"success": True, "customers": customers_data})


@app.route("/api/customers/<customer_id>", methods=["GET"])
def get_customer_details(customer_id):
    customer = bank_app.engine.customer_mgr.get(customer_id)
    if not customer:
        return jsonify({"success": False, "message": f"Customer {customer_id} not found"}), 404

    curr_date = bank_app.current_date
    fds = [
        {
            "fd_id": d.fd_id,
            "principal": d.principal,
            "initial_principal": d.initial_principal,
            "rate_pct": d.rate_pct,
            "tenure_days": d.tenure_days,
            "fd_type": d.fd_type,
            "maturity_instruction": d.maturity_instruction,
            "booking_date": d.booking_date.strftime("%Y-%m-%d"),
            "value_date": d.value_date.strftime("%Y-%m-%d"),
            "maturity_date": d.maturity_date.strftime("%Y-%m-%d"),
            "maturity_value": d.maturity_value,
            "status": d.status,
            "lien": d.lien,
            "loan_principal": d.loan_principal,
        }
        for d in bank_app.engine.booking_service.deposits.values()
        if d.customer_id == customer_id
    ]

    return jsonify({
        "success": True,
        "customer": {
            "customer_id": customer.customer_id,
            "customer_name": customer.customer_name,
            "date_of_birth": customer.date_of_birth.strftime("%Y-%m-%d"),
            "is_senior": customer.is_senior(curr_date),
            "pan": customer.pan,
            "form_15g_15h": customer.form_15g_15h,
            "tds_rate": customer.get_tds_rate(),
            "savings_account_no": customer.savings_account_no,
            "fy_interest": customer.fy_interest,
            "fy_tds": customer.fy_tds,
            "fds": fds,
        }
    })


@app.route("/api/customers", methods=["POST"])
def create_customer():
    data = request.get_json() or {}
    cust_id = data.get("customer_id", "").strip().upper()
    name = data.get("customer_name", "").strip()
    dob_str = data.get("date_of_birth", "").strip()
    pan = data.get("pan", "").strip().upper()
    form_15 = bool(data.get("form_15g_15h", False))
    sb_acc = data.get("savings_account_no", "").strip()

    if not cust_id:
        return jsonify({"success": False, "message": "Customer ID is required"}), 400
    if not name:
        return jsonify({"success": False, "message": "Customer Name is required"}), 400
    if not dob_str:
        return jsonify({"success": False, "message": "Date of Birth is required"}), 400
    if not sb_acc:
        return jsonify({"success": False, "message": "Savings Account Number is required"}), 400

    try:
        dob = datetime.date.fromisoformat(dob_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid Date of Birth format (YYYY-MM-DD required)"}), 400

    if bank_app.engine.customer_mgr.get(cust_id):
        return jsonify({"success": False, "message": f"Customer ID {cust_id} already exists"}), 400

    new_cust = Customer(
        customer_id=cust_id,
        customer_name=name,
        date_of_birth=dob,
        pan=pan,
        form_15g_15h=form_15,
        savings_account_no=sb_acc,
    )
    bank_app.engine.customer_mgr.customers[cust_id] = new_cust

    return jsonify({
        "success": True,
        "message": f"Customer {cust_id} created successfully",
        "customer": {
            "customer_id": cust_id,
            "customer_name": name,
            "date_of_birth": dob_str,
            "pan": pan,
            "form_15g_15h": form_15,
            "savings_account_no": sb_acc,
        }
    })


# ==============================================================================
# Rate Cards & Interest Calculator APIs
# ==============================================================================

@app.route("/api/rate-cards", methods=["GET"])
def get_rate_cards():
    cards = []
    for cid, entries in bank_app.engine.rate_card_mgr.cards.items():
        for e in entries:
            cards.append({
                "card_id": e.card_id,
                "effective_from": e.effective_from.strftime("%Y-%m-%d"),
                "tenure_band": e.tenure_band,
                "min_days": e.min_days,
                "max_days": e.max_days,
                "amount_band": e.amount_band,
                "rate_pct": e.rate_pct,
                "senior_addon_pct": e.senior_addon_pct,
            })
    return jsonify({"success": True, "rate_cards": cards})


@app.route("/api/fd/preview-rate", methods=["POST"])
def preview_booking_rate():
    data = request.get_json() or {}
    customer_id = data.get("customer_id", "").strip()
    try:
        amount = float(data.get("amount", 0))
        tenure_value = int(data.get("tenure_value", 0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid amount or tenure value"}), 400

    tenure_unit = data.get("tenure_unit", "M").strip().upper()
    fd_type = data.get("fd_type", "CUMULATIVE").strip().upper()
    booking_date_str = data.get("booking_date") or bank_app.current_date.strftime("%Y-%m-%d")

    try:
        b_date = datetime.date.fromisoformat(booking_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid booking date format"}), 400

    customer = bank_app.engine.customer_mgr.get(customer_id)
    is_senior = customer.is_senior(b_date) if customer else False

    # Compute tenure days & maturity date
    if tenure_unit == "D":
        mat_date = b_date + datetime.timedelta(days=tenure_value)
    elif tenure_unit == "M":
        mat_date = add_months(b_date, tenure_value)
    else:
        return jsonify({"success": False, "message": "Invalid tenure unit. Must be 'D' or 'M'"}), 400

    tenure_days = (mat_date - b_date).days

    # Validation checks according to business rules
    validation_error = None
    if amount < 5000.0:
        validation_error = "Minimum booking amount is Rs 5,000"
    elif tenure_days < 7:
        validation_error = "Minimum tenure is 7 days"
    elif tenure_days > 3650:
        validation_error = "Maximum tenure is 10 years (3,650 days)"

    if validation_error:
        return jsonify({
            "success": False,
            "message": validation_error,
            "tenure_days": tenure_days,
            "maturity_date": mat_date.strftime("%Y-%m-%d"),
            "is_senior": is_senior,
        }), 400

    try:
        card_id, base_rate, effective_rate = bank_app.engine.rate_card_mgr.get_applicable_rate(
            value_date=b_date,
            principal=amount,
            tenure_days=tenure_days,
            is_senior=is_senior
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

    if fd_type == "CUMULATIVE":
        projected_maturity = project_cumulative_maturity_value(
            principal=amount,
            rate_pct=effective_rate,
            start_date=b_date,
            end_date=mat_date
        )
        total_interest = round(projected_maturity - amount, 2)
    elif fd_type == "MONTHLY_PAYOUT":
        projected_maturity = amount
        # Monthly payout estimate
        monthly_int = calculate_monthly_interest(amount, effective_rate)
        total_interest = round(monthly_int * (tenure_days / 30.416), 2)
    else:  # QUARTERLY_PAYOUT
        projected_maturity = amount
        quarterly_int = calculate_quarterly_interest(amount, effective_rate)
        total_interest = round(quarterly_int * (tenure_days / 91.25), 2)

    return jsonify({
        "success": True,
        "card_id": card_id,
        "base_rate": base_rate,
        "senior_addon": round(effective_rate - base_rate, 2),
        "effective_rate": effective_rate,
        "is_senior": is_senior,
        "tenure_days": tenure_days,
        "booking_date": b_date.strftime("%Y-%m-%d"),
        "maturity_date": mat_date.strftime("%Y-%m-%d"),
        "projected_maturity_value": round(projected_maturity, 2),
        "total_estimated_interest": round(total_interest, 2),
    })


@app.route("/api/calculate-interest", methods=["POST"])
def calculate_interest_tool():
    """Standalone calculator endpoint for arbitrary queries using exact business logic."""
    data = request.get_json() or {}
    try:
        principal = float(data.get("principal", 0))
        rate_pct = float(data.get("rate_pct", 0))
        tenure_value = int(data.get("tenure_value", 0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid numeric inputs"}), 400

    tenure_unit = data.get("tenure_unit", "M").strip().upper()
    calc_type = data.get("type", "CUMULATIVE").strip().upper()
    start_date_str = data.get("start_date") or bank_app.current_date.strftime("%Y-%m-%d")

    try:
        start_date = datetime.date.fromisoformat(start_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid start date format"}), 400

    if principal <= 0:
        return jsonify({"success": False, "message": "Principal must be greater than 0"}), 400
    if rate_pct < 0:
        return jsonify({"success": False, "message": "Interest rate cannot be negative"}), 400

    if tenure_unit == "D":
        end_date = start_date + datetime.timedelta(days=tenure_value)
    else:
        end_date = add_months(start_date, tenure_value)

    tenure_days = (end_date - start_date).days

    # Monthly payout
    monthly_payout = calculate_monthly_interest(principal, rate_pct)
    # Quarterly payout
    quarterly_payout = calculate_quarterly_interest(principal, rate_pct)
    # Cumulative maturity value
    cumulative_maturity = project_cumulative_maturity_value(
        principal=principal,
        rate_pct=rate_pct,
        start_date=start_date,
        end_date=end_date
    )

    return jsonify({
        "success": True,
        "principal": principal,
        "rate_pct": rate_pct,
        "tenure_days": tenure_days,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "monthly_payout": monthly_payout,
        "quarterly_payout": quarterly_payout,
        "cumulative_maturity_value": cumulative_maturity,
        "cumulative_interest_earned": round(cumulative_maturity - principal, 2),
    })


# ==============================================================================
# Fixed Deposit Lifecycle APIs
# ==============================================================================

@app.route("/api/fds", methods=["GET"])
def list_deposits():
    status_filter = request.args.get("status", "").strip().upper()
    cust_filter = request.args.get("customer_id", "").strip().upper()

    fds = []
    for fd in bank_app.engine.booking_service.deposits.values():
        if status_filter and fd.status != status_filter:
            continue
        if cust_filter and fd.customer_id != cust_filter:
            continue

        cust = bank_app.engine.customer_mgr.get(fd.customer_id)
        cust_name = cust.customer_name if cust else "Unknown"

        fds.append({
            "fd_id": fd.fd_id,
            "customer_id": fd.customer_id,
            "customer_name": cust_name,
            "card_id": fd.card_id,
            "principal": fd.principal,
            "initial_principal": fd.initial_principal,
            "tenure_value": fd.tenure_value,
            "tenure_unit": fd.tenure_unit,
            "tenure_days": fd.tenure_days,
            "fd_type": fd.fd_type,
            "maturity_instruction": fd.maturity_instruction,
            "booking_date": fd.booking_date.strftime("%Y-%m-%d"),
            "value_date": fd.value_date.strftime("%Y-%m-%d"),
            "maturity_date": fd.maturity_date.strftime("%Y-%m-%d"),
            "rate_pct": fd.rate_pct,
            "maturity_value": fd.maturity_value,
            "status": fd.status,
            "renewed_as": fd.renewed_as,
            "lien": fd.lien,
            "loan_principal": fd.loan_principal,
        })

    # Sort descending by booking date / fd_id
    fds.sort(key=lambda x: (x["booking_date"], x["fd_id"]), reverse=True)
    return jsonify({"success": True, "deposits": fds})


@app.route("/api/fds/<fd_id>", methods=["GET"])
def get_deposit_details(fd_id):
    fd = bank_app.engine.booking_service.deposits.get(fd_id)
    if not fd:
        return jsonify({"success": False, "message": f"Fixed Deposit {fd_id} not found"}), 404

    cust = bank_app.engine.customer_mgr.get(fd.customer_id)
    events = [
        {
            "date": evt.date.strftime("%Y-%m-%d"),
            "event": evt.event,
            "amount": evt.amount,
            "tds": evt.tds,
            "net_amount": evt.net_amount,
            "principal_after": evt.principal_after,
            "note": evt.note,
        }
        for evt in bank_app.engine.events
        if evt.fd_id == fd_id
    ]

    return jsonify({
        "success": True,
        "deposit": {
            "fd_id": fd.fd_id,
            "customer_id": fd.customer_id,
            "customer_name": cust.customer_name if cust else "",
            "card_id": fd.card_id,
            "principal": fd.principal,
            "initial_principal": fd.initial_principal,
            "tenure_value": fd.tenure_value,
            "tenure_unit": fd.tenure_unit,
            "tenure_days": fd.tenure_days,
            "fd_type": fd.fd_type,
            "maturity_instruction": fd.maturity_instruction,
            "booking_date": fd.booking_date.strftime("%Y-%m-%d"),
            "value_date": fd.value_date.strftime("%Y-%m-%d"),
            "maturity_date": fd.maturity_date.strftime("%Y-%m-%d"),
            "rate_pct": fd.rate_pct,
            "maturity_value": fd.maturity_value,
            "status": fd.status,
            "renewed_as": fd.renewed_as,
            "lien": fd.lien,
            "loan_principal": fd.loan_principal,
            "events": events,
        }
    })


@app.route("/api/fd/book", methods=["POST"])
def book_fixed_deposit():
    data = request.get_json() or {}
    fd_id = data.get("fd_id", "").strip().upper()
    customer_id = data.get("customer_id", "").strip().upper()
    try:
        amount = float(data.get("amount", 0))
        tenure_value = int(data.get("tenure_value", 0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Amount and tenure must be valid numbers"}), 400

    tenure_unit = data.get("tenure_unit", "M").strip().upper()
    fd_type = data.get("fd_type", "CUMULATIVE").strip().upper()
    instruction = data.get("maturity_instruction", "PAYOUT").strip().upper()
    booking_date_str = data.get("booking_date") or bank_app.current_date.strftime("%Y-%m-%d")

    if not fd_id:
        # Auto-generate next FD ID if omitted
        existing_nums = [
            int(k.replace("FD-", "").split("-")[0])
            for k in bank_app.engine.booking_service.deposits.keys()
            if k.startswith("FD-") and k.replace("FD-", "").split("-")[0].isdigit()
        ]
        next_num = max(existing_nums, default=0) + 1
        fd_id = f"FD-{next_num:04d}"

    if fd_id in bank_app.engine.booking_service.deposits:
        return jsonify({"success": False, "message": f"FD ID {fd_id} already exists"}), 400

    try:
        b_date = datetime.date.fromisoformat(booking_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid booking date format"}), 400

    # Ensure simulation clock is at least up to booking date
    if bank_app.engine.current_sim_date and b_date > bank_app.engine.current_sim_date:
        bank_app.engine.advance_time_to(b_date)
    elif not bank_app.engine.current_sim_date:
        bank_app.engine.current_sim_date = b_date

    try:
        fd = bank_app.engine.booking_service.book_fd(
            fd_id=fd_id,
            customer_id=customer_id,
            amount=amount,
            tenure_value=tenure_value,
            tenure_unit=tenure_unit,
            fd_type=fd_type,
            instruction=instruction,
            booking_date=b_date,
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

    if fd.status == "REJECTED":
        # Determine why it was rejected
        reason = "Validation failed"
        if amount < 5000:
            reason = "Minimum booking amount is Rs 5,000"
        elif fd.tenure_days < 7:
            reason = "Minimum tenure is 7 days"
        elif fd.tenure_days > 3650:
            reason = "Maximum tenure is 10 years (3,650 days)"
        return jsonify({"success": False, "message": f"Booking Rejected: {reason}"}), 400

    # Log the successful booking event
    bank_app.engine.log_event(
        fd_id=fd.fd_id,
        dt=b_date,
        event="BOOKING",
        amount=fd.principal,
        tds=0.0,
        net_amount=fd.principal,
        principal_after=fd.principal,
        note="Fixed Deposit booked via Web Portal"
    )

    return jsonify({
        "success": True,
        "message": f"Fixed Deposit {fd.fd_id} booked successfully!",
        "deposit": {
            "fd_id": fd.fd_id,
            "customer_id": fd.customer_id,
            "card_id": fd.card_id,
            "principal": fd.principal,
            "tenure_days": fd.tenure_days,
            "rate_pct": fd.rate_pct,
            "maturity_date": fd.maturity_date.strftime("%Y-%m-%d"),
            "maturity_value": fd.maturity_value,
            "status": fd.status,
        }
    })


@app.route("/api/fd/backdate", methods=["POST"])
def backdate_fixed_deposit():
    data = request.get_json() or {}
    fd_id = data.get("fd_id", "").strip().upper()
    val_date_str = data.get("value_date", "").strip()

    try:
        v_date = datetime.date.fromisoformat(val_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid value date format (YYYY-MM-DD)"}), 400

    success = bank_app.engine.booking_service.backdate_fd(fd_id, v_date)
    if not success:
        return jsonify({
            "success": False,
            "message": "Backdate rejected! Can only backdate up to 3 days back for active deposits booked same day."
        }), 400

    fd = bank_app.engine.booking_service.deposits[fd_id]
    bank_app.engine.log_event(
        fd_id=fd_id,
        dt=v_date,
        event="BACKDATE",
        amount=fd.principal,
        tds=0.0,
        net_amount=fd.principal,
        principal_after=fd.principal,
        note=f"Deposit value-dated back to {val_date_str}"
    )

    return jsonify({
        "success": True,
        "message": f"FD {fd_id} backdated successfully to {val_date_str}",
        "new_value_date": val_date_str,
        "new_maturity_date": fd.maturity_date.strftime("%Y-%m-%d"),
        "new_rate_pct": fd.rate_pct,
        "new_maturity_value": fd.maturity_value,
    })


@app.route("/api/fd/withdraw", methods=["POST"])
def premature_withdrawal():
    data = request.get_json() or {}
    fd_id = data.get("fd_id", "").strip().upper()
    w_date_str = data.get("date") or bank_app.current_date.strftime("%Y-%m-%d")
    amount_str = str(data.get("amount", "FULL")).strip()

    try:
        w_date = datetime.date.fromisoformat(w_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid withdrawal date format"}), 400

    # Advance time if necessary
    if bank_app.engine.current_sim_date and w_date > bank_app.engine.current_sim_date:
        bank_app.engine.advance_time_to(w_date)

    success, msg, p_withdrawn, g_int, tds, net_p = (
        bank_app.engine.maturity_service.process_premature_withdrawal(fd_id, w_date, amount_str)
    )

    if not success:
        return jsonify({"success": False, "message": msg}), 400

    fd = bank_app.engine.booking_service.deposits[fd_id]
    bank_app.engine.log_event(
        fd_id=fd_id,
        dt=w_date,
        event="PREMATURE_WITHDRAW",
        amount=p_withdrawn,
        tds=tds,
        net_amount=net_p,
        principal_after=fd.principal,
        note=f"Premature withdrawal of Rs {p_withdrawn:.2f}"
    )

    if tds > 0:
        bank_app.engine.tds_records.append(
            TDSStatementRecord(
                customer_id=fd.customer_id,
                fy=get_financial_year(w_date),
                fd_id=fd_id,
                date=w_date,
                interest_amount=g_int,
                tds_rate_pct=bank_app.engine.customer_mgr.get(fd.customer_id).get_tds_rate(),
                tds_amount=tds,
            )
        )

    return jsonify({
        "success": True,
        "message": "Premature withdrawal processed successfully",
        "details": {
            "fd_id": fd_id,
            "status_after": fd.status,
            "principal_withdrawn": p_withdrawn,
            "gross_interest": g_int,
            "tds_deducted": tds,
            "net_payout": net_p,
            "remaining_principal": fd.principal,
        }
    })


@app.route("/api/fd/renew", methods=["POST"])
def manual_renew_fd():
    data = request.get_json() or {}
    fd_id = data.get("fd_id", "").strip().upper()
    r_date_str = data.get("date") or bank_app.current_date.strftime("%Y-%m-%d")

    try:
        r_date = datetime.date.fromisoformat(r_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid renewal date"}), 400

    fd = bank_app.engine.booking_service.deposits.get(fd_id)
    if not fd:
        return jsonify({"success": False, "message": f"FD {fd_id} not found"}), 404

    if fd.status not in ("ACTIVE", "MATURED"):
        return jsonify({"success": False, "message": f"Cannot renew FD with status {fd.status}"}), 400

    renewal_principal = fd.principal
    renewed_fd = bank_app.engine.maturity_service.execute_renewal(fd, r_date, renewal_principal)

    bank_app.engine.log_event(
        fd_id=fd_id,
        dt=r_date,
        event="RENEWAL",
        amount=renewal_principal,
        tds=0.0,
        net_amount=renewal_principal,
        principal_after=0.0,
        note=f"Manual renewal into {renewed_fd.fd_id}"
    )

    return jsonify({
        "success": True,
        "message": f"Deposit renewed successfully as {renewed_fd.fd_id}",
        "old_fd_id": fd_id,
        "new_fd_id": renewed_fd.fd_id,
        "new_principal": renewed_fd.principal,
        "new_maturity_date": renewed_fd.maturity_date.strftime("%Y-%m-%d"),
        "new_rate_pct": renewed_fd.rate_pct,
    })


@app.route("/api/fd/loan", methods=["POST"])
def sanction_loan():
    data = request.get_json() or {}
    fd_id = data.get("fd_id", "").strip().upper()
    l_date_str = data.get("date") or bank_app.current_date.strftime("%Y-%m-%d")
    amt_str = str(data.get("amount", "MAX")).strip().upper()

    try:
        l_date = datetime.date.fromisoformat(l_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid loan date format"}), 400

    fd = bank_app.engine.booking_service.deposits.get(fd_id)
    if not fd or fd.status != "ACTIVE":
        return jsonify({"success": False, "message": "Deposit must be ACTIVE to sanction a loan"}), 400

    max_allowed = round(0.90 * fd.principal, 2)
    if amt_str == "MAX":
        loan_amt = max_allowed
    else:
        try:
            loan_amt = float(amt_str)
        except ValueError:
            return jsonify({"success": False, "message": "Invalid loan amount"}), 400

    if loan_amt <= 0:
        return jsonify({"success": False, "message": "Loan amount must be greater than zero"}), 400
    if loan_amt > max_allowed:
        return jsonify({"success": False, "message": f"Loan amount exceeds 90% limit (Max allowed: Rs {max_allowed:.2f})"}), 400

    fd.loan_principal = round(fd.loan_principal + loan_amt, 2)
    fd.lien = True

    bank_app.engine.log_event(
        fd_id=fd_id,
        dt=l_date,
        event="LOAN_DISBURSED",
        amount=loan_amt,
        tds=0.0,
        net_amount=loan_amt,
        principal_after=fd.principal,
        note=f"Loan against FD sanctioned (Lien active). Total loan: Rs {fd.loan_principal:.2f}"
    )

    return jsonify({
        "success": True,
        "message": f"Loan of Rs {loan_amt:.2f} sanctioned successfully against FD {fd_id}",
        "loan_principal": fd.loan_principal,
        "lien": fd.lien,
    })


@app.route("/api/fd/loan-repay", methods=["POST"])
def repay_loan():
    data = request.get_json() or {}
    fd_id = data.get("fd_id", "").strip().upper()
    r_date_str = data.get("date") or bank_app.current_date.strftime("%Y-%m-%d")
    amt_str = str(data.get("amount", "FULL")).strip().upper()

    try:
        r_date = datetime.date.fromisoformat(r_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid repayment date"}), 400

    fd = bank_app.engine.booking_service.deposits.get(fd_id)
    if not fd or fd.loan_principal <= 0:
        return jsonify({"success": False, "message": "No active loan found for this deposit"}), 400

    if amt_str == "FULL":
        repay_amt = fd.loan_principal
    else:
        try:
            repay_amt = float(amt_str)
        except ValueError:
            return jsonify({"success": False, "message": "Invalid repayment amount"}), 400

    fd.loan_principal = round(max(0.0, fd.loan_principal - repay_amt), 2)
    if fd.loan_principal == 0.0:
        fd.lien = False

    bank_app.engine.log_event(
        fd_id=fd_id,
        dt=r_date,
        event="LOAN_REPAY",
        amount=repay_amt,
        tds=0.0,
        net_amount=repay_amt,
        principal_after=fd.principal,
        note="Loan fully repaid; lien released" if not fd.lien else f"Partial loan repayment of Rs {repay_amt:.2f}"
    )

    return jsonify({
        "success": True,
        "message": f"Repayment of Rs {repay_amt:.2f} recorded",
        "remaining_loan": fd.loan_principal,
        "lien_active": fd.lien,
    })


@app.route("/api/fd/claim", methods=["POST"])
def claim_maturity():
    data = request.get_json() or {}
    fd_id = data.get("fd_id", "").strip().upper()
    c_date_str = data.get("date") or bank_app.current_date.strftime("%Y-%m-%d")

    try:
        c_date = datetime.date.fromisoformat(c_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid claim date"}), 400

    fd = bank_app.engine.booking_service.deposits.get(fd_id)
    if not fd or fd.status not in ("ACTIVE", "MATURED"):
        return jsonify({"success": False, "message": "FD must be ACTIVE or MATURED to claim payout"}), 400

    payout_amt = fd.principal
    fd.principal = 0.0
    fd.status = "CLOSED"

    bank_app.engine.log_event(
        fd_id=fd_id,
        dt=c_date,
        event="CLAIM",
        amount=payout_amt,
        tds=0.0,
        net_amount=payout_amt,
        principal_after=0.0,
        note="Maturity proceeds claimed and credited to savings account"
    )

    return jsonify({
        "success": True,
        "message": f"Maturity proceeds of Rs {payout_amt:.2f} successfully paid out for {fd_id}",
        "payout_amount": payout_amt,
        "status": fd.status,
    })


# ==============================================================================
# Simulation & Time Travel APIs
# ==============================================================================

@app.route("/api/simulation/advance-date", methods=["POST"])
def advance_simulation_date():
    data = request.get_json() or {}
    target_date_str = data.get("target_date", "").strip()

    try:
        target_date = datetime.date.fromisoformat(target_date_str)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid date format. Expected YYYY-MM-DD"}), 400

    if bank_app.engine.current_sim_date and target_date < bank_app.engine.current_sim_date:
        return jsonify({
            "success": False,
            "message": f"Cannot travel backwards. Current date is {bank_app.engine.current_sim_date}"
        }), 400

    initial_events_count = len(bank_app.engine.events)
    bank_app.engine.advance_time_to(target_date)
    new_events_count = len(bank_app.engine.events) - initial_events_count

    return jsonify({
        "success": True,
        "message": f"Simulation advanced to {target_date_str}. Generated {new_events_count} automated daily lifecycle events.",
        "new_current_date": target_date_str,
        "automated_events_generated": new_events_count,
    })


@app.route("/api/simulation/reset", methods=["POST"])
def reset_simulation():
    bank_app.load_initial_data()
    return jsonify({
        "success": True,
        "message": "Simulation reinitialized with original CSVs and commands pack.",
        "current_date": bank_app.current_date.strftime("%Y-%m-%d"),
    })


# ==============================================================================
# Reports & Evaluation CSV Export APIs
# ==============================================================================

@app.route("/api/reports/advices", methods=["GET"])
def get_advices_report():
    advices = []
    # If advice requests were logged by commands, return those; otherwise return all deposits
    req_ids = bank_app.engine.advice_requests or list(bank_app.engine.booking_service.deposits.keys())
    for fid in req_ids:
        fd = bank_app.engine.booking_service.deposits.get(fid)
        if fd:
            advices.append({
                "fd_id": fd.fd_id,
                "customer_id": fd.customer_id,
                "card_id": fd.card_id,
                "booking_date": fd.booking_date.strftime("%Y-%m-%d"),
                "value_date": fd.value_date.strftime("%Y-%m-%d"),
                "maturity_date": fd.maturity_date.strftime("%Y-%m-%d"),
                "tenure_days": fd.tenure_days,
                "principal": fd.initial_principal,
                "rate_pct": fd.rate_pct,
                "type": fd.fd_type,
                "instruction": fd.maturity_instruction,
                "maturity_value": fd.maturity_value,
                "status": fd.status,
                "renewed_as": fd.renewed_as,
            })
    return jsonify({"success": True, "advices": advices})


@app.route("/api/reports/events", methods=["GET"])
def get_events_report():
    events_data = [
        {
            "fd_id": evt.fd_id,
            "date": evt.date.strftime("%Y-%m-%d"),
            "event": evt.event,
            "amount": evt.amount,
            "tds": evt.tds,
            "net_amount": evt.net_amount,
            "principal_after": evt.principal_after,
            "note": evt.note,
        }
        for evt in bank_app.engine.events
    ]
    return jsonify({"success": True, "events": events_data})


@app.route("/api/reports/interest-certificates", methods=["GET"])
def get_certificates_report():
    certs = []
    # If cert requests exist from commands.txt, use them; else summarize all customers across FYs
    if bank_app.engine.cert_requests:
        for cid, fy in bank_app.engine.cert_requests:
            cust = bank_app.engine.customer_mgr.get(cid)
            if cust:
                certs.append({
                    "customer_id": cid,
                    "customer_name": cust.customer_name,
                    "fy": fy,
                    "interest_paid_or_credited": cust.fy_interest.get(fy, 0.0),
                    "tds_deducted": cust.fy_tds.get(fy, 0.0),
                    "fd_count": len(cust.fy_fds.get(fy, set())),
                })
    else:
        for cust in bank_app.engine.customer_mgr.customers.values():
            for fy, interest in cust.fy_interest.items():
                certs.append({
                    "customer_id": cust.customer_id,
                    "customer_name": cust.customer_name,
                    "fy": fy,
                    "interest_paid_or_credited": interest,
                    "tds_deducted": cust.fy_tds.get(fy, 0.0),
                    "fd_count": len(cust.fy_fds.get(fy, set())),
                })
    return jsonify({"success": True, "certificates": certs})


@app.route("/api/reports/tds-statements", methods=["GET"])
def get_tds_report():
    records = [
        {
            "customer_id": r.customer_id,
            "fy": r.fy,
            "fd_id": r.fd_id,
            "date": r.date.strftime("%Y-%m-%d"),
            "interest_amount": r.interest_amount,
            "tds_rate_pct": r.tds_rate_pct,
            "tds_amount": r.tds_amount,
        }
        for r in bank_app.engine.tds_records
    ]
    return jsonify({"success": True, "records": records})


@app.route("/api/reports/download/<filename>", methods=["GET"])
def download_csv_report(filename):
    allowed_files = {
        "fd_advices.csv": "fd_advices.csv",
        "fd_events.csv": "fd_events.csv",
        "interest_certificates.csv": "interest_certificates.csv",
        "tds_statement.csv": "tds_statement.csv",
    }
    if filename not in allowed_files:
        return jsonify({"success": False, "message": "Invalid report name"}), 404

    # Regenerate current state to CSV
    bank_app.engine.generate_outputs(output_dir=".")
    filepath = os.path.abspath(filename)
    if not os.path.exists(filepath):
        return jsonify({"success": False, "message": "Report file not found"}), 404

    return send_file(filepath, as_attachment=True, download_name=filename, mimetype="text/csv")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Fixed Deposit Banking Web App on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
