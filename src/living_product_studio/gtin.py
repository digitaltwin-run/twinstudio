from __future__ import annotations


def calculate_check_digit(body: str) -> str:
    """Calculate the GS1 mod-10 check digit for a numeric body.

    The function validates number composition only. It does not allocate a GTIN or
    confer the right to use a company prefix.
    """

    if not body.isdigit() or not body:
        raise ValueError("GTIN body must contain digits only")
    total = 0
    for index, digit in enumerate(reversed(body)):
        total += int(digit) * (3 if index % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def complete_gtin(body: str, *, total_length: int = 13) -> str:
    if total_length not in {8, 12, 13, 14}:
        raise ValueError("GTIN length must be 8, 12, 13, or 14")
    if len(body) != total_length - 1:
        raise ValueError(f"Expected {total_length - 1} body digits for GTIN-{total_length}")
    return body + calculate_check_digit(body)


def validate_gtin(value: str) -> bool:
    return bool(value.isdigit() and len(value) in {8, 12, 13, 14} and calculate_check_digit(value[:-1]) == value[-1])
