"""Book replay validator on generated files."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from helpers import book_lines, book_message, zip_bytes
from hft_crypto.data.book_replay import replay_stream, replay_zip
from hft_crypto.data.parsers import ValidationError


def replay(*messages: dict[str, object]):  # type: ignore[no-untyped-def]
    return replay_stream(io.BytesIO(book_lines(messages)))


SNAPSHOT = book_message("snapshot", 1, [["100.0", "1"], ["99.0", "2"]], [["101.0", "1"], ["102.0", "2"]])


def test_a_clean_file_passes_with_exact_counts() -> None:
    result = replay(
        SNAPSHOT,
        book_message("delta", 2, [["100.0", "3"]], []),
        book_message("delta", 3, [], [["101.0", "0"]]),
    )
    assert result.ok
    assert result.lines == 3
    assert result.snapshots == 1
    assert result.deltas == 2
    assert result.update_id_breaks == 0
    assert result.crossed == 0
    assert result.crossed_checks == 3
    assert result.first_ts_ms == 1001
    assert result.last_ts_ms == 1003
    assert result.depth_topic == "orderbook.200.BTCUSDT"


def test_a_skipped_update_id_is_a_break() -> None:
    result = replay(SNAPSHOT, book_message("delta", 2, [], []), book_message("delta", 4, [], []))
    assert result.update_id_breaks == 1
    assert result.break_examples == [{"previous_u": 2, "u": 4}]
    assert not result.ok


def test_a_repeated_delta_id_is_a_break() -> None:
    result = replay(SNAPSHOT, book_message("delta", 2, [], []), book_message("delta", 2, [], []))
    assert result.update_id_breaks == 1


def test_a_crossed_book_is_caught() -> None:
    result = replay(SNAPSHOT, book_message("delta", 2, [["101.5", "1"]], []))
    assert result.crossed == 1
    assert not result.ok


def test_a_locked_book_counts_as_crossed() -> None:
    result = replay(SNAPSHOT, book_message("delta", 2, [["101.0", "1"]], []))
    assert result.crossed == 1


def test_deleting_the_best_level_exposes_the_next_one() -> None:
    """If removal failed, the old best bid would still be compared and this would look crossed."""
    result = replay(
        SNAPSHOT,
        book_message("delta", 2, [["100.0", "0"]], []),
        book_message("delta", 3, [], [["100.5", "1"]]),
    )
    assert result.crossed == 0
    assert result.ok


def test_mid_file_snapshot_matching_the_rebuilt_book_passes() -> None:
    # A periodic snapshot restates the book, repeating the id of the delta before it.
    result = replay(
        SNAPSHOT,
        book_message("delta", 2, [["100.0", "5"]], [["101.0", "0"]]),
        book_message("snapshot", 2, [["100.0", "5"], ["99.0", "2"]], [["102.0", "2"]]),
        book_message("delta", 3, [["99.5", "1"]], []),
    )
    assert result.ok
    assert result.snapshots == 2
    assert result.snapshot_comparisons == 1
    assert result.snapshot_mismatches == 0
    assert result.update_id_breaks == 0


def test_mid_file_snapshot_disagreeing_with_the_rebuilt_book_fails() -> None:
    result = replay(
        SNAPSHOT,
        book_message("delta", 2, [["100.0", "5"]], []),
        book_message("snapshot", 2, [["100.0", "4"], ["99.0", "2"]], [["101.0", "1"], ["102.0", "2"]]),
    )
    assert result.snapshot_mismatches == 1
    assert not result.ok


def test_a_snapshot_replaces_the_book() -> None:
    result = replay(
        SNAPSHOT,
        book_message("snapshot", 2, [["50.0", "1"]], [["51.0", "1"]]),
        book_message("delta", 3, [["50.5", "1"]], []),
    )
    assert result.crossed == 0
    assert result.max_levels_per_side == 2


def test_a_service_restart_snapshot_is_a_reset_and_not_a_break() -> None:
    """F-19. It used to restate the same book, and never asked whether the day passed."""
    new_book = book_message("snapshot", 1, [["90.0", "7"], ["89.0", "2"]], [["91.0", "1"], ["92.0", "2"]])
    result = replay(
        SNAPSHOT,
        book_message("delta", 2, [], []),
        new_book,
        book_message("delta", 2, [], []),
    )
    assert result.update_id_resets == 1
    assert result.update_id_breaks == 0
    assert result.snapshot_mismatches == 0
    assert result.ok is True


def test_a_snapshot_that_is_not_a_reset_still_has_to_agree() -> None:
    result = replay(SNAPSHOT, book_message("snapshot", 2, [["90.0", "7"]], [["91.0", "1"]]))
    assert result.snapshot_mismatches == 1
    assert result.ok is False


@pytest.mark.parametrize("size", ["-1", "NaN", "inf"], ids=["negative", "nan", "infinite"])
def test_a_size_that_cannot_be_real_is_malformed(size: str) -> None:
    """F-19. These passed."""
    result = replay(SNAPSHOT, book_message("delta", 2, [["100.0", size]], []))
    assert result.malformed_lines == 1
    assert result.ok is False


def test_a_file_with_an_empty_side_never_checked_for_a_crossed_book_does_not_pass() -> None:
    """F-19. With no ask at all, nothing could ever cross, and that passed."""
    result = replay(book_message("snapshot", 1, [["100.0", "1"]], []))
    assert result.crossed_checks == 0
    assert result.ok is False


def test_a_snapshot_that_jumps_is_a_break() -> None:
    result = replay(SNAPSHOT, book_message("snapshot", 9, [["100.0", "1"]], [["101.0", "1"]]))
    assert result.update_id_breaks == 1


def test_deleting_a_level_that_is_not_there_is_counted() -> None:
    result = replay(SNAPSHOT, book_message("delta", 2, [["55.0", "0"]], []))
    assert result.deletes_of_absent_level == 1


def test_malformed_lines_fail_without_stopping_the_replay() -> None:
    stream = io.BytesIO(
        book_lines([SNAPSHOT]) + b"this is not json\n" + book_lines([book_message("delta", 2, [], [])])
    )
    result = replay_stream(stream)
    assert result.malformed_lines == 1
    assert result.lines == 3
    assert not result.ok


def test_an_empty_file_does_not_pass() -> None:
    assert not replay_stream(io.BytesIO(b"")).ok


def test_a_file_with_no_snapshot_does_not_pass() -> None:
    assert not replay(book_message("delta", 2, [], [])).ok


def test_replay_reads_from_a_zip_without_extracting(tmp_path: Path) -> None:
    path = tmp_path / "x.data.zip"
    path.write_bytes(zip_bytes("x.data", book_lines([SNAPSHOT]).decode()))
    result = replay_zip(path)
    assert result.ok
    assert [p.name for p in tmp_path.iterdir()] == ["x.data.zip"]


def test_a_bad_zip_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.data.zip"
    path.write_bytes(b"garbage")
    with pytest.raises(ValidationError):
        replay_zip(path)


def test_result_serialises_with_its_verdict() -> None:
    result = replay(SNAPSHOT)
    assert result.to_dict()["ok"] is True


def test_a_corrupt_zip_is_a_malformed_result_and_not_a_traceback(tmp_path: Path) -> None:
    """N-10. `replay_zip` was the fourth reader, and the fixes file said three. 16 of 400 fuzzed files ended
    this way."""
    lines = [book_message("delta", index, [[str(100 + index % 7), "1"]], []) for index in range(1, 4000)]
    body = zip_bytes("x.data", book_lines(lines).decode("utf-8"))
    middle = len(body) // 3
    path = tmp_path / "x.zip"
    path.write_bytes(body[:middle] + bytes(b ^ 0xFF for b in body[middle : middle + 8]) + body[middle + 8 :])
    with pytest.raises(ValidationError):
        replay_zip(path)
