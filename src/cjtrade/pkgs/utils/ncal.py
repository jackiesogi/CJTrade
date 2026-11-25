#!/usr/bin/env python3
"""
ncal.py - Cross-platform calendar display utility
Mimics the behavior of Unix ncal command with horizontal layout
"""
import calendar
import sys
from datetime import datetime
from typing import Optional

from cjtrade.pkgs.logger import get_console
from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.logger import setup_logging

log = get_logger("utils")
out = get_console()


def display_calendar(target_date: Optional[datetime] = None, monday_first: bool = True,
                     highlight: bool = True) -> None:
    """Display a calendar for the given date's month.

    Parameters
    ----------
    target_date : datetime, optional
        Month to show and day to highlight; defaults to now.
    monday_first : bool
        Start weeks on Monday; otherwise Sunday.
    highlight : bool
        Show the target day in inverse video.

    Warnings
    --------
    Calls ``calendar.setfirstweekday``, which changes a process-wide setting.
    """
    if target_date is None:
        target_date = datetime.now()

    year = target_date.year
    month = target_date.month
    day = target_date.day

    # Set first day of week (0=Monday, 6=Sunday)
    calendar.setfirstweekday(0 if monday_first else 6)

    # Get month calendar
    cal = calendar.monthcalendar(year, month)

    # Month and year header
    month_name = calendar.month_name[month]
    header = f"{month_name} {year}"
    out.info(header.center(20))

    # Day names header
    if monday_first:
        day_names = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
    else:
        day_names = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']

    out.info(' '.join(day_names))

    # Print each week
    for week in cal:
        week_str = []
        for d in week:
            if d == 0:
                # Empty day (padding)
                week_str.append('  ')
            elif highlight and d == day:
                # Highlight the target day with inverse video
                week_str.append(f'\033[7m{d:2d}\033[0m')
            else:
                week_str.append(f'{d:2d}')
        out.info(' '.join(week_str))

    out.info("")  # Blank line at the end


def main():
    """Main entry point for command-line usage."""
    setup_logging()
    import argparse

    parser = argparse.ArgumentParser(description='Display a calendar')
    parser.add_argument('date', nargs='?', help='Date string (e.g., "2026-02-10" or "Feb 10, 2026")')
    parser.add_argument('-m', '--monday', action='store_true', default=True,
                       help='Start week on Monday (default)')
    parser.add_argument('-s', '--sunday', action='store_true',
                       help='Start week on Sunday')
    parser.add_argument('--no-highlight', action='store_true',
                       help='Don\'t highlight the target date')

    args = parser.parse_args()

    # Parse date if provided
    target_date = None
    if args.date:
        try:
            # Try various date formats
            for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y',
                       '%b %d, %Y', '%B %d, %Y', '%Y-%m-%d %H:%M:%S']:
                try:
                    target_date = datetime.strptime(args.date, fmt)
                    break
                except ValueError:
                    continue

            if target_date is None:
                # Try parsing with dateutil if available
                try:
                    from dateutil import parser as date_parser
                    target_date = date_parser.parse(args.date)
                except (ImportError, ValueError):
                    log.error("unable to parse date %r", args.date)
                    sys.exit(1)
        except Exception as e:
            log.error("parse date failed: %s", e)
            sys.exit(1)

    # Determine first day of week
    monday_first = not args.sunday if args.sunday else args.monday

    display_calendar(target_date, monday_first=monday_first,
                    highlight=not args.no_highlight)


if __name__ == '__main__':
    main()
