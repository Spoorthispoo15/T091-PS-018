"""
Main entry point for the Fixed Deposit Booking, Renewal and Premature Withdrawal Engine.
Team ID: T091
Project ID: PS-018
"""

import sys
import os
from src.command_processor import CommandProcessor


def main():
    print("=" * 70)
    print("PS-018: Fixed Deposit Booking, Renewal & Premature Withdrawal Engine")
    print("Team T091 | College Capstone Project")
    print("=" * 70)

    data_dir = "data"
    commands_file = os.path.join(data_dir, "commands.txt")

    if not os.path.exists(commands_file):
        print(f"Error: {commands_file} not found!")
        sys.exit(1)

    print(f"\n[1/3] Initializing CommandProcessor with data directory: {data_dir}")
    engine = CommandProcessor(data_dir=data_dir)

    print(f"[2/3] Processing event stream from: {commands_file} ...")
    engine.execute_command_file(commands_file)

    print("[3/3] Generating evaluation CSV reports ...")
    engine.generate_outputs(output_dir=".")

    print("\nSuccessfully generated the following output files:")
    print("  - fd_advices.csv")
    print("  - fd_events.csv")
    print("  - interest_certificates.csv")
    print("  - tds_statement.csv")
    print("\nExecution completed successfully!")


if __name__ == "__main__":
    main()
