"""Shared validation and pacing for API mutation runs."""
import time


def parse_delay_seconds(data):
    value = data.get('delay_seconds', 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('"delay_seconds" must be a number between 0 and 60.')
    if not 0 <= value <= 60:
        raise ValueError('"delay_seconds" must be a number between 0 and 60.')
    return value


def wait_between_cases(delay_seconds):
    if delay_seconds > 0:
        time.sleep(delay_seconds)
