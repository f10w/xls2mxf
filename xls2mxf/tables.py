"""Traffic sheet parsing: blocks, IDs, dates, filenames."""
import datetime as _dt
from pathlib import Path

import openpyxl

from .constants import HEADER_TEXT, EXT, DATE_RE
from .errors import AssemblyError


def _find_id_column(ws) -> int | None:
    """Searches for the column with HEADER_TEXT header. Returns (col_index 1-based,
    header_row) or None. Searches within the first 10 rows of the sheet."""
    for row in ws.iter_rows(min_row=1, max_row=10):
        for cell in row:
            if isinstance(cell.value, str) and cell.value.strip() == HEADER_TEXT:
                return cell.column, cell.row
    return None



def extract_ids(xlsx_path: Path) -> set:
    """Extracts integer IDs from the column found by the 'ID ролика' header.
    Works regardless of which column (F, J, ...) it occupies."""
    ids = set()
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        found = _find_id_column(ws)
        if not found:
            continue  # this sheet has no ID column
        col, header_row = found
        for row in ws.iter_rows(min_row=header_row + 1, min_col=col, max_col=col,
                                values_only=True):
            val = row[0]
            if val is None:
                continue
            if isinstance(val, str):
                s = val.strip()
                if not s.isdigit():
                    continue
                ids.add(int(s))
            elif isinstance(val, (int, float)) and float(val).is_integer():
                ids.add(int(val))
    wb.close()
    return ids



def find_xlsx_for_date(xlsx_dir: Path, ddmmyy: str) -> list:
    out = []
    for x in sorted(xlsx_dir.glob("*.xlsx")):
        if x.name.startswith("~$"):
            continue
        m = DATE_RE.search(x.stem)
        if m and m.group(1) == ddmmyy:
            out.append(x)
    return out



def read_id_column_raw(xlsx_path: Path, customlines: list) -> list:
    """Reads the 'ID ролика' column TOP-TO-BOTTOM as-is: no sorting, no dedup.
    Each gap (one or more empty rows between data blocks) is replaced with
    exactly three customlines entries. Leading and trailing empty rows are dropped.

    Returns a list of strings ready for line-by-line paste (like a column in Excel)."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb.active
    found = _find_id_column(ws)
    if not found:
        wb.close()
        return []
    col, header_row = found

    # collect raw column values below the header: cell value as string or None
    raw = []
    for row in ws.iter_rows(min_row=header_row + 1, min_col=col, max_col=col,
                            values_only=True):
        v = row[0]
        if v is None or (isinstance(v, str) and v.strip() == ""):
            raw.append(None)
        elif isinstance(v, float) and v.is_integer():
            raw.append(str(int(v)))
        else:
            raw.append(str(v).strip())
    wb.close()

    # strip leading and trailing empty entries
    start, end = 0, len(raw)
    while start < end and raw[start] is None:
        start += 1
    while end > start and raw[end - 1] is None:
        end -= 1
    raw = raw[start:end]

    # any internal gap (one or more consecutive Nones) -> 3 custom lines
    result = []
    i = 0
    n = len(raw)
    while i < n:
        if raw[i] is not None:
            result.append(raw[i])
            i += 1
        else:
            # skip the entire run of empty cells
            while i < n and raw[i] is None:
                i += 1
            result.extend(customlines)
    return result



def parse_blocks(xlsx_path: Path) -> list:
    """Slices a traffic sheet into blocks. Returns a list of dicts:
       {time: 'HH:MM', ids: [int,...], itogo: int|None}.
    A block = consecutive rows with a number in the ID column; terminated by an
    empty-ID row. Time comes from column A of the first row of the block. ИТОГО
    comes from column E ('Хрон.') in the row where column D == 'ИТОГО'."""
    import datetime as _dt
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb.active
    found = _find_id_column(ws)
    if not found:
        wb.close()
        raise AssemblyError(f"Column 'ID ролика' not found in {xlsx_path.name}.")
    id_col, header_row = found

    blocks = []
    cur_ids = []
    cur_chron = {}      # {id: duration from column E} for the current block
    cur_time = None
    pending_itogo = None

    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        a_val = row[0] if len(row) > 0 else None
        d_val = row[3] if len(row) > 3 else None
        e_val = row[4] if len(row) > 4 else None
        id_val = row[id_col - 1] if len(row) >= id_col else None

        # normalise ID
        fid = None
        if isinstance(id_val, int):
            fid = id_val
        elif isinstance(id_val, float) and id_val.is_integer():
            fid = int(id_val)
        elif isinstance(id_val, str) and id_val.strip().isdigit():
            fid = int(id_val.strip())

        if fid is not None:
            cur_ids.append(fid)
            # clip duration from column E (keyed by id; one value per id)
            if isinstance(e_val, (int, float)):
                cur_chron[fid] = int(e_val)
            if cur_time is None:
                if isinstance(a_val, _dt.time):
                    cur_time = a_val.strftime("%H:%M")
                elif a_val not in (None, ""):
                    cur_time = str(a_val).strip()
        else:
            # row without ID — could be ИТОГО or blank
            if isinstance(d_val, str) and d_val.strip().upper() == "ИТОГО":
                if isinstance(e_val, (int, float)):
                    pending_itogo = int(e_val)
            # close the block: accumulated clips + encountered a gap
            if cur_ids and (id_val is None or id_val == ""):
                # close only on the first fully blank row (no ID, no ИТОГО marker)
                is_blank = (a_val in (None, "")) and (d_val in (None, "")) and (id_val in (None, ""))
                if is_blank:
                    blocks.append({"time": cur_time, "ids": cur_ids,
                                   "chron": cur_chron, "itogo": pending_itogo})
                    cur_ids = []
                    cur_chron = {}
                    cur_time = None
                    pending_itogo = None
    if cur_ids:
        blocks.append({"time": cur_time, "ids": cur_ids,
                       "chron": cur_chron, "itogo": pending_itogo})
    wb.close()
    return blocks



def time_to_filepart(t: str) -> str:
    """'05:25' -> '05-25'. Returns 'unknown' when time is None."""
    if not t:
        return "unknown"
    return t.replace(":", "-")



def ddmmyy_to_dashed(ddmmyy: str) -> str:
    """'170626' -> '17-06-26'."""
    return f"{ddmmyy[0:2]}-{ddmmyy[2:4]}-{ddmmyy[4:6]}"


# ---------- file existence check (handler 1) ----------


def check_all_files_exist(blocks: list, src_dir: Path) -> list:
    """Returns list of (block_index, missing_id). Empty list means all files present."""
    missing = []
    for bi, b in enumerate(blocks):
        for fid in b["ids"]:
            if not (src_dir / f"{fid}{EXT}").is_file():
                missing.append((bi, fid))
    return missing


# ---------- ffmpeg command helpers ----------
