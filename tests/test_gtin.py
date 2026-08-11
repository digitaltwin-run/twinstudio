from living_product_studio.gtin import calculate_check_digit, complete_gtin, validate_gtin


def test_gtin_check_digit_known_example() -> None:
    # GS1 examples commonly use 4006381333931; body check digit is 1.
    assert calculate_check_digit("400638133393") == "1"
    assert complete_gtin("400638133393", total_length=13) == "4006381333931"
    assert validate_gtin("4006381333931")
    assert not validate_gtin("4006381333932")
