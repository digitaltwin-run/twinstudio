from living_product_studio.uri import PoaUriError, build_poa_uri, is_within_scope, parse_poa_uri


def test_poa_round_trip_and_scope() -> None:
    parent = build_poa_uri("demo", "project", "main", "part", "base")
    child = parent + "/feature/shell"
    parsed = parse_poa_uri(child)
    assert parsed.tenant == "demo"
    assert parsed.project == "project"
    assert parsed.revision == "main"
    assert parsed.segments[-2:] == ("feature", "shell")
    assert is_within_scope(child, [parent])
    assert not is_within_scope("poa://other/project@main/part/base", [parent])


def test_revision_can_be_ignored_only_explicitly() -> None:
    assert not is_within_scope(
        "poa://demo/project@rev-2/part/base/feature/shell",
        ["poa://demo/project@main/part/base"],
    )
    assert is_within_scope(
        "poa://demo/project@rev-2/part/base/feature/shell",
        ["poa://demo/project@main/part/base"],
        ignore_revision=True,
    )


def test_invalid_uri_rejected() -> None:
    try:
        parse_poa_uri("https://example.test/project")
    except PoaUriError:
        pass
    else:
        raise AssertionError("invalid scheme accepted")
