import re
from collections import Counter

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import GroupedInvoice


INVOICE_SEQ_RE = re.compile(r"-(\d+)$")


def parse_sequence(invoice_number):
    if not invoice_number:
        return None
    match = INVOICE_SEQ_RE.search(invoice_number)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def iter_missing_ranges(numbers):
    numbers = sorted(numbers)
    if not numbers:
        return []
    ranges = []
    start = prev = numbers[0]
    for value in numbers[1:]:
        if value == prev + 1:
            prev = value
            continue
        ranges.append((start, prev))
        start = prev = value
    ranges.append((start, prev))
    return ranges


class Command(BaseCommand):
    help = "List missing invoice sequence numbers for GroupedInvoice."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            dest="user",
            help="Filter by user id or username.",
        )
        parser.add_argument(
            "--start",
            type=int,
            help="Override start of sequence (default: min found).",
        )
        parser.add_argument(
            "--end",
            type=int,
            help="Override end of sequence (default: max found).",
        )
        parser.add_argument(
            "--ranges",
            action="store_true",
            help="Print missing numbers as ranges.",
        )
        parser.add_argument(
            "--duplicates",
            action="store_true",
            help="List duplicate sequence numbers (with counts).",
        )
        parser.add_argument(
            "--odd-only",
            action="store_true",
            help="When used with --duplicates, show only odd sequence numbers.",
        )

    def handle(self, *args, **options):
        user_value = options.get("user")
        start_override = options.get("start")
        end_override = options.get("end")
        as_ranges = options.get("ranges")
        show_duplicates = options.get("duplicates")
        odd_only = options.get("odd_only")

        qs = GroupedInvoice.objects.exclude(invoice_number__isnull=True).exclude(invoice_number="")

        if user_value:
            User = get_user_model()
            if user_value.isdigit():
                user = User.objects.filter(id=int(user_value)).first()
            else:
                user = User.objects.filter(username=user_value).first()
            if not user:
                raise CommandError(f"User not found: {user_value}")
            qs = qs.filter(user=user)

        invoice_numbers = list(qs.values_list("invoice_number", flat=True))
        sequences_raw = [parse_sequence(value) for value in invoice_numbers]
        sequences = sorted({value for value in sequences_raw if value is not None})

        if not sequences and start_override is None and end_override is None:
            self.stdout.write("No invoice numbers found.")
            return

        start = start_override if start_override is not None else (sequences[0] if sequences else None)
        end = end_override if end_override is not None else (sequences[-1] if sequences else None)

        if start is None or end is None:
            raise CommandError("Cannot determine start/end; provide --start and --end.")
        if start > end:
            raise CommandError("--start cannot be greater than --end.")

        if show_duplicates:
            counts = Counter(value for value in sequences_raw if value is not None)
            duplicates = [
                (value, count)
                for value, count in counts.items()
                if count > 1 and start <= value <= end
            ]
            if odd_only:
                duplicates = [(value, count) for value, count in duplicates if value % 2 == 1]
            if not duplicates:
                self.stdout.write("No duplicate invoice numbers.")
                return
            for value, count in sorted(duplicates):
                self.stdout.write(f"{value} ({count})")
            return

        missing = sorted(set(range(start, end + 1)) - set(sequences))

        if not missing:
            self.stdout.write("No missing invoice numbers.")
            return

        if as_ranges:
            ranges = iter_missing_ranges(missing)
            for start, end in ranges:
                if start == end:
                    self.stdout.write(str(start))
                else:
                    self.stdout.write(f"{start}-{end}")
            return

        for value in missing:
            self.stdout.write(str(value))
