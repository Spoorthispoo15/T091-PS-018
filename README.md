# PS-018: Fixed Deposit Booking, Renewal & Premature Withdrawal Engine

**Team ID:** T091  
**Project ID:** PS-018  
**Domain:** Core Banking & FinTech System  
**Stack:** Python, Flask, HTML5, CSS3, JavaScript (ES6)

---

## 📌 Project Overview

**PS-018 Fixed Deposit Engine** is a full-featured core banking simulation and web platform that automates the complete lifecycle of Fixed Deposits according to Indian banking guidelines and tax rules.

The system handles everything from initial customer verification, rate card band lookups, senior citizen interest add-ons, monthly and quarterly payouts, quarter-end compounding, backdating, loan against FD (with lien enforcement), premature withdrawals (with day 7 vs day 8 penalty rules), weekend/holiday roll-overs (+3% savings rate), and TDS tracking with retroactive deduction upon crossing the ₹40,000 threshold.

---

## 🚀 Key Features

### 1. Executive Banking Dashboard
* **Real-time KPI Metrics:** Active Deposits Principal, Projected Maturity Value, Cumulative Interest Paid/Credited, Total TDS Deducted, and Managed Customers.
* **Live Event Stream:** Interactive audit trail tracking bookings, interest payouts, compounding credits, renewals, premature closures, and loan disbursements.
* **System Simulation Date:** Dynamic date progression engine simulating banking days.

### 2. Customer Profile Management
* **Depositor Directory:** Profiles with DOB, PAN, savings account numbers, and Form 15G/15H submission status.
* **Dynamic Senior Citizen Tagging:** Automatically determines senior citizen status ($\ge 60$ years) based on booking date.
* **TDS Tracking:** Enforces $0\%$ TDS for Form 15G/15H, $20\%$ for missing PAN, and $10\%$ standard rate with FY tracking.

### 3. Fixed Deposit Booking Portal
* **Live Dynamic Rate Matching:** Instant preview of applicable rate card (`RC-2023` / `RC-2025`), base rate, senior add-on ($+0.50\%$), and scheduled maturity value.
* **Scheme Flexibility:** Supports `CUMULATIVE` (quarterly compounding), `MONTHLY_PAYOUT` (discounted factor $0.9975/12$), and `QUARTERLY_PAYOUT` (simple $\text{rate}/4$).
* **Backdating:** Allows value-dating a deposit up to 3 days back with automatic re-pricing.

### 4. Lifecycle Actions & Master Ledger
* **Premature Withdrawal:** Enforces Day $\le 7$ rule ($0\%$ interest, $0\%$ penalty) and Day $> 7$ rule (re-priced at tenure rate minus $1\%$ penalty).
* **Partial Withdrawal:** Enforces multiples of ₹1,000 and minimum remaining balance of ₹5,000.
* **Loan Against FD:** Sanction loans up to $90\%$ of deposit principal with automatic lien placement blocking premature withdrawal until fully repaid.
* **FD Renewal:** Automated 14-day renewal for unclaimed payout deposits, sequential renewal IDs (`FD-xxxx-R1`), and manual renewal workflows.
* **Official Printable Advice:** Generates official Fixed Deposit Advice certificates with print support.

### 5. Regulatory & Evaluation Reports
Direct access and downloadable evaluation CSV files:
* `fd_advices.csv`
* `fd_events.csv`
* `interest_certificates.csv`
* `tds_statement.csv`

---

## 🛠️ Project Architecture

```
T091-PS-018/
├── app.py                      # Flask Backend API wrapping existing business logic
├── requirements.txt            # Python dependencies (Flask)
├── .gitignore                  # Git ignore rules
├── templates/
│   └── index.html              # Modern, responsive single-page Banking Dashboard UI
├── static/
│   ├── css/
│   │   └── style.css           # Banking design system (Apex Trust Bank)
│   └── js/
│       └── app.js              # Client-side controller, live rate preview, modals & APIs
├── data/
│   ├── customers.csv           # Depositor sample records
│   ├── rate_cards.csv          # Rate card versions (RC-2023, RC-2025) by tenure & amount bands
│   ├── holidays.csv            # Bank holidays calendar
│   ├── commands.txt            # 171 benchmark command lines
│   └── README.md               # Original project specifications & test case mappings
├── src/
│   ├── customer.py             # Customer dataclass, CustomerManager & TDS engine
│   ├── rate_card.py            # RateCardManager, effective dates & band matching
│   ├── interest_calculation.py # Discounted monthly, quarterly, broken stubs & penalties
│   ├── fd_booking.py           # FixedDeposit model, compounding & booking service
│   ├── maturity_process.py     # MaturityService, holiday rollovers & premature withdrawals
│   └── command_processor.py    # Simulation engine, daily jobs scheduler & CSV outputs
├── test_booking.py             # Booking unit tests
├── test_interest.py            # Interest calculation unit tests
├── test_maturity.py            # Maturity & withdrawal unit tests
├── test_web_api.py             # Web API integration test suite
└── main.py                     # CLI batch runner
```

---

## 💻 Installation & Setup

### Prerequisites
* Python 3.10+ installed

### 1. Clone the Repository
```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the Web Application
```bash
python app.py
```
Open **[http://127.0.0.1:5000](http://127.0.0.1:5000)** in your web browser.

### 4. (Optional) Run CLI Simulation
```bash
python main.py
```

---

## 🧪 Running Automated Tests

Run the complete test suite (all 34 tests):
```bash
python -m unittest discover -s . -p "test_*.py"
```

---

## 📄 License
Academic Capstone Project — Team T091.
