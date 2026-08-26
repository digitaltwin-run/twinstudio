from types import SimpleNamespace

from twinstudio.artifact_group_review import review_artifact_group


def test_group_review_is_bounded_and_read_only(tmp_path) -> None:
    firmware = tmp_path / "firmware" / "code.py"
    firmware.parent.mkdir()
    firmware.write_text("import board\nKEY = board.GP1\n", encoding="utf-8")
    settings = SimpleNamespace(subllm_enabled=False, litellm_model="")

    review = review_artifact_group(
        tmp_path,
        "firmware",
        ["firmware/code.py"],
        "Sprawdź firmware pod kątem GPIO i testów.",
        settings,
    )

    assert review.mode.startswith("local-fallback")
    assert review.files[0].included is True
    assert review.requires_human_review is True
    assert "GPIO" in review.summary
