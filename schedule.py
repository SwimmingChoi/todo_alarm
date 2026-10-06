"""일정.txt 읽기/쓰기와 날짜 해석. (UI 없음)"""
import os
import re
from datetime import date
from pathlib import Path
from typing import NamedTuple

# exe 위치와 무관한 고정 경로: exe를 옮기거나 여러 곳에서 실행해도 같은 일정을 본다
SCHEDULE_FILE = Path(os.environ.get("APPDATA") or Path.home()) / "todo_alarm" / "일정.txt"

SAMPLE = """\
# 일정 파일 - 프로그램 창에서 추가/삭제하거나, 여기에 직접 적어도 됩니다.
# 한 줄에 "날짜 내용" 형식. '#'으로 시작하는 줄은 무시됩니다.
#
# 2026-10-06 치과 예약     (그 날 하루만)
# 10-06 엄마 생신          (매년 반복)
"""

# 2026-10-06 / 2026.10.6. / 10/6 등을 허용. 연도가 없으면 매년 반복.
LINE_RE = re.compile(r"(?:(\d{4})\s*[-./]\s*)?(\d{1,2})\s*[-./]\s*(\d{1,2})\.?\s+(.+)")


class Entry(NamedTuple):
    raw: str  # 파일의 원본 줄 (삭제할 때 식별용)
    year: int | None  # None이면 매년 반복
    month: int
    day: int
    text: str

    def next_ymd(self, today: date) -> tuple[int, int, int]:
        """다음에 돌아오는 (연, 월, 일). 매년 반복이면 올해 또는 내년."""
        if self.year is not None:
            return (self.year, self.month, self.day)
        passed = (self.month, self.day) < (today.month, today.day)
        return (today.year + passed, self.month, self.day)


def _is_real_date(year: int | None, month: int, day: int) -> bool:
    try:
        date(year or 2024, month, day)  # 매년 반복은 윤년 기준 (02-29 허용)
    except ValueError:
        return False
    return True


def parse(lines: list[str]) -> tuple[list[Entry], list[str]]:
    """(일정 목록, 날짜를 해석하지 못한 줄 목록)을 반환."""
    entries, bad = [], []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.fullmatch(line)
        if not m:
            bad.append(line)
            continue
        entry = Entry(line, int(m[1]) if m[1] else None, int(m[2]), int(m[3]), m[4])
        if _is_real_date(entry.year, entry.month, entry.day):
            entries.append(entry)
        else:
            bad.append(line)  # 02-30처럼 없는 날짜는 영원히 알림이 안 오므로 오류로 알린다
    return entries, bad


def todays(lines: list[str], today: date) -> tuple[list[str], list[str]]:
    """(오늘 일정 내용 목록, 날짜를 해석하지 못한 줄 목록)을 반환."""
    entries, bad = parse(lines)
    ymd = (today.year, today.month, today.day)
    return [e.text for e in entries if e.next_ymd(today) == ymd], bad


def read_lines() -> list[str]:
    if not SCHEDULE_FILE.exists():
        return []
    data = SCHEDULE_FILE.read_bytes()
    # 메모장 저장 형식 대비: UTF-8(BOM 유무), UTF-16("유니코드"), ANSI(cp949)
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16").splitlines()
    try:
        return data.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        return data.decode("cp949").splitlines()


def write_lines(lines: list[str]) -> None:
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULE_FILE.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    os.replace(tmp, SCHEDULE_FILE)  # 알림 프로세스가 반쯤 쓰인 파일을 읽지 않도록 원자적 교체


def add(year: int | None, month: int, day: int, text: str) -> None:
    """일정 한 줄 추가. year가 None이면 매년 반복. 입력이 잘못되면 ValueError."""
    text = " ".join(text.split())
    if not text:
        raise ValueError("내용을 입력하세요.")
    if not _is_real_date(year, month, day):
        raise ValueError("존재하지 않는 날짜입니다.")
    if year is not None and year < 1000:
        raise ValueError("연도는 4자리로 입력하세요.")
    prefix = f"{year:04d}-" if year is not None else ""
    write_lines(read_lines() + [f"{prefix}{month:02d}-{day:02d} {text}"])


def delete(raw: str) -> None:
    """원본 줄이 raw인 일정 하나를 삭제 (같은 줄이 여러 개면 첫 번째만)."""
    lines = read_lines()
    for i, line in enumerate(lines):
        if line.strip() == raw:
            del lines[i]
            break
    write_lines(lines)


def selftest() -> None:
    import tempfile

    global SCHEDULE_FILE
    today = date(2026, 10, 6)
    items, bad = todays(
        [
            "# 주석", "", "2026-10-06 치과", "10-06 생일", "2026. 10. 6. 회의", "10/6 운동",
            "2025-10-06 작년", "2026-10-07 내일", "02-29 윤년", "13-40 엉터리", "02-30 없는 날", "날짜없음",
        ],
        today,
    )
    assert items == ["치과", "생일", "회의", "운동"], items
    assert bad == ["13-40 엉터리", "02-30 없는 날", "날짜없음"], bad
    assert Entry("", None, 10, 5, "").next_ymd(today) == (2027, 10, 5)

    # 파일 추가/삭제 왕복: 주석은 보존되고, 잘못된 입력은 거부
    with tempfile.TemporaryDirectory() as tmp:
        SCHEDULE_FILE = Path(tmp) / "새 폴더" / "일정.txt"
        assert read_lines() == []
        write_lines(SAMPLE.splitlines())
        add(2026, 10, 6, "  치과\n예약 ")
        add(None, 2, 29, "윤년 생일")
        for args in [(2026, 2, 30, "x"), (2026, 10, 6, "  "), (26, 10, 6, "x")]:
            try:
                add(*args)
            except ValueError:
                continue
            raise AssertionError(args)
        entries, bad = parse(read_lines())
        assert [e.raw for e in entries] == ["2026-10-06 치과 예약", "02-29 윤년 생일"] and not bad, entries
        delete("2026-10-06 치과 예약")
        assert read_lines() == SAMPLE.splitlines() + ["02-29 윤년 생일"], read_lines()
        for encoding in ("utf-16", "cp949", "utf-8"):
            SCHEDULE_FILE.write_text("10-06 한글 일정\n", encoding=encoding)
            assert read_lines() == ["10-06 한글 일정"], encoding
    print("selftest ok")


if __name__ == "__main__":
    selftest()
