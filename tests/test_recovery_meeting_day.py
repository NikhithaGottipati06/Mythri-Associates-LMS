import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import _build_period_filter, _coerce_week_type, _is_recovery_posting_due


def test_meeting_day_cutoff_uses_next_meeting_for_same_week_disbursement():
    # Wednesday disbursement for a Thursday meeting center should not appear on the
    # immediately following Thursday because the first posting is due after one week.
    assert _is_recovery_posting_due('30/07/2026', '29/07/2026', 'Thursday') is False


def test_meeting_day_cutoff_allows_next_week_for_later_disbursement():
    assert _is_recovery_posting_due('06/08/2026', '29/07/2026', 'Thursday') is True


def test_period_filter_requires_only_from_and_to_dates():
    clause, params = _build_period_filter('10/01/2025', '15/01/2025', 'm.date_of_join')
    assert clause == "substr(m.date_of_join,7,4)||'-'||substr(m.date_of_join,4,2)||'-'||substr(m.date_of_join,1,2) >= ? AND substr(m.date_of_join,7,4)||'-'||substr(m.date_of_join,4,2)||'-'||substr(m.date_of_join,1,2) <= ?"
    assert params == ('2025-01-10', '2025-01-15')


def test_week_type_coerces_string_and_blank_values():
    assert _coerce_week_type('21') == 21
    assert _coerce_week_type('') is None
    assert _coerce_week_type(None) is None


if __name__ == '__main__':
    test_meeting_day_cutoff_uses_next_meeting_for_same_week_disbursement()
    test_meeting_day_cutoff_allows_next_week_for_later_disbursement()
    print('recovery meeting-day tests passed')
