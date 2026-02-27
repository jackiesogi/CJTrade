#!/usr/bin/env python3
"""
date.py - Cross-platform date utility
Mimics the behavior of GNU date command with Unix timestamp support
"""
import locale
import sys
from datetime import datetime


def format_date(dt: datetime, format_str: str = None) -> str:
    """
    Format a datetime object.
    """
    if format_str:
        return dt.strftime(format_str)

    # Default format similar to GNU date
    # Example: "Wed Feb  4 09:04:06 Taipei Standard Time 2026"
    try:
        # Try to get timezone name
        tz_name = dt.astimezone().tzname()
        if not tz_name:
            tz_name = "UTC"
    except:
        tz_name = "UTC"

    # Format: Day Mon DD HH:MM:SS TZ YYYY
    weekday = dt.strftime('%a')
    month = dt.strftime('%b')
    day = dt.strftime('%e').strip()  # Day with leading space instead of zero
    time_str = dt.strftime('%H:%M:%S')
    year = dt.strftime('%Y')

    return f"{weekday} {month} {day:>2} {time_str} {tz_name} {year}"


def parse_date_string(date_str: str) -> datetime:
    """
    Parse various date string formats.

    Args:
        date_str: Date string to parse

    Returns:
        Parsed datetime object

    Raises:
        ValueError: If the date string cannot be parsed
    """
    # Handle Unix timestamp format: @1234567890
    if date_str.startswith('@'):
        try:
            timestamp = float(date_str[1:])
            return datetime.fromtimestamp(timestamp)
        except (ValueError, OSError) as e:
            raise ValueError(f"Invalid timestamp: {date_str}") from e

    # Handle "now"
    if date_str.lower() == 'now':
        return datetime.now()

    # Handle "today"
    if date_str.lower() == 'today':
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Handle "yesterday"
    if date_str.lower() == 'yesterday':
        from datetime import timedelta
        return (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Handle "tomorrow"
    if date_str.lower() == 'tomorrow':
        from datetime import timedelta
        return (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Try common date formats
    formats = [
        '%Y-%m-%d',
        '%Y/%m/%d',
        '%m/%d/%Y',
        '%d/%m/%Y',
        '%Y-%m-%d %H:%M:%S',
        '%Y/%m/%d %H:%M:%S',
        '%m/%d/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M:%S',
        '%b %d, %Y',
        '%B %d, %Y',
        '%d %b %Y',
        '%d %B %Y',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    raise ValueError(f"Unable to parse date string: {date_str}")


def main():
    """Main entry point for command-line usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Display or parse date and time',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          Display current date and time
  %(prog)s -d "@1234567890"         Display date from Unix timestamp
  %(prog)s -d "2026-02-10"          Display specific date
  %(prog)s -d "now"                 Display current date and time
  %(prog)s -d "@1234567890" +"%%Y-%%m-%%d"  Format output
        """
    )

    parser.add_argument('-d', '--date', metavar='STRING',
                       help='Display time described by STRING (e.g., "@1234567890", "2026-02-10", "now")')
    parser.add_argument('format', nargs='?',
                       help='Output format (strftime format, must start with +)')
    parser.add_argument('-u', '--utc', '--universal', action='store_true',
                       help='Print or set Coordinated Universal Time (UTC)')
    parser.add_argument('-I', '--iso-8601', nargs='?', const='date', metavar='TIMESPEC',
                       help='Output ISO 8601 format')
    parser.add_argument('-R', '--rfc-email', action='store_true',
                       help='Output RFC 5322 format')

    args = parser.parse_args()

    # Determine the datetime to display
    try:
        if args.date:
            dt = parse_date_string(args.date)
        else:
            dt = datetime.now()

        if args.utc:
            dt = dt.utcnow() if not args.date else dt

        # Determine output format
        if args.format:
            # Format string starts with +
            if args.format.startswith('+'):
                format_str = args.format[1:]
                output = dt.strftime(format_str)
            else:
                print(f"Error: Format must start with '+'", file=sys.stderr)
                sys.exit(1)
        elif args.iso_8601:
            if args.iso_8601 == 'date':
                output = dt.strftime('%Y-%m-%d')
            elif args.iso_8601 == 'hours':
                output = dt.strftime('%Y-%m-%dT%H%z')
            elif args.iso_8601 == 'minutes':
                output = dt.strftime('%Y-%m-%dT%H:%M%z')
            elif args.iso_8601 == 'seconds':
                output = dt.strftime('%Y-%m-%dT%H:%M:%S%z')
            else:
                output = dt.isoformat()
        elif args.rfc_email:
            output = dt.strftime('%a, %d %b %Y %H:%M:%S %z')
        else:
            # Default format
            output = format_date(dt)

        print(output)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
