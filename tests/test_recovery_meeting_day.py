import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import _is_recovery_posting_due


def test_meeting_day_cutoff_uses_next_meeting_for_same_week_disbursement():
    # Wednesday disbursement for a Thursday meeting center should not appear on the
    # immediately following Thursday because the first posting is due after one week.
    assert _is_recovery_posting_due('30/07/2026', '29/07/2026', 'Thursday') is False


def test_meeting_day_cutoff_allows_next_week_for_later_disbursement():
    assert _is_recovery_posting_due('06/08/2026', '29/07/2026', 'Thursday') is True


if __name__ == '__main__':
    test_meeting_day_cutoff_uses_next_meeting_for_same_week_disbursement()
    test_meeting_day_cutoff_allows_next_week_for_later_disbursement()
    print('recovery meeting-day tests passed')
