import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from gspread.utils import rowcol_to_a1
from datetime import datetime
import io
import re
import csv
import time

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
TEACHER_PASSWORD = "marylee_13"

HEADERS = {
    "topics": ["id", "grade", "subject", "title", "product", "is_booked", "booked_by", "booked_at", "deadline"],
    "submissions": ["id", "topic_id", "student_name", "student_class", "filename",
                    "drive_file_id", "drive_link", "status", "teacher_comment", "submitted_at", "updated_at",
                    "status_history", "versions"],
    "materials": ["id", "title", "description", "filename", "drive_file_id", "drive_link", "uploaded_at"],
    "questions": ["id", "student_name", "student_class", "topic_title", "question", "answer",
                  "status", "created_at", "answered_at"],
    "announcements": ["id", "title", "text", "is_active", "created_at", "updated_at"],
    "action_log": ["id", "timestamp", "actor", "action", "details"],
}


@st.cache_resource
def get_google_clients():
    try:
        creds_info = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(credentials)
        drive_service = build("drive", "v3", credentials=credentials)
        return gc, drive_service
    except Exception as e:
        st.error("Ошибка подключения к Google. Проверьте Secrets.")
        st.exception(e)
        st.stop()


@st.cache_resource
def _open_spreadsheet():
    gc, _ = get_google_clients()
    sheet_id = str(st.secrets["SPREADSHEET_ID"]).strip()
    last_err = None
    for attempt in range(5):
        try:
            return gc.open_by_key(sheet_id)
        except Exception as e:
            last_err = e
            wait = 3 * (attempt + 1)
            if "429" in str(e) or "Quota" in str(e):
                wait = 15 * (attempt + 1)
            time.sleep(wait)
    raise last_err


def get_spreadsheet():
    try:
        return _open_spreadsheet()
    except Exception as e:
        st.error(
            "Не удалось открыть Google Таблицу. "
            "Чаще всего это лимит API (429). Подождите 1–2 минуты и обновите страницу один раз."
        )
        st.exception(e)
        st.stop()


def get_drive_folder_id():
    return str(st.secrets["DRIVE_FOLDER_ID"]).strip()


def ensure_worksheet(name):
    ss = get_spreadsheet()
    try:
        return ss.worksheet(name)
    except Exception as e:
        from gspread.exceptions import WorksheetNotFound
        if not isinstance(e, WorksheetNotFound):
            raise
        headers = HEADERS.get(name, ["id"])
        try:
            ws = ss.add_worksheet(title=name, rows=2000, cols=max(len(headers), 14))
            ws.update("A1", [headers], value_input_option="USER_ENTERED")
            time.sleep(0.3)
            return ws
        except Exception:
            return ss.worksheet(name)


@st.cache_resource
def init_sheets():
    ss = get_spreadsheet()
    existing_titles = {ws.title for ws in ss.worksheets()}
    for name, headers in HEADERS.items():
        if name not in existing_titles:
            try:
                ws = ss.add_worksheet(title=name, rows=2000, cols=max(len(headers), 14))
                ws.update("A1", [headers], value_input_option="USER_ENTERED")
                time.sleep(0.5)
            except Exception:
                pass
    return True


def ensure_all_sheets():
    ss = get_spreadsheet()
    existing_titles = {ws.title for ws in ss.worksheets()}
    for name, headers in HEADERS.items():
        if name not in existing_titles:
            try:
                ws = ss.add_worksheet(title=name, rows=2000, cols=max(len(headers), 14))
                ws.update("A1", [headers], value_input_option="USER_ENTERED")
                time.sleep(0.4)
            except Exception:
                pass
    return True


def safe_get_all_values(ws, retries=4):
    last_err = None
    for attempt in range(retries):
        try:
            return ws.get_all_values()
        except Exception as e:
            last_err = e
            wait = 2 * (attempt + 1)
            if "429" in str(e) or "Quota" in str(e):
                wait = 20 * (attempt + 1)
            time.sleep(wait)
    raise last_err


def rows_to_records(values, expected_headers=None):
    if not values or len(values) < 1:
        return []
    headers = [str(h).strip() for h in values[0]]
    while headers and headers[-1] == "":
        headers.pop()
    if not headers:
        return []
    records = []
    for row in values[1:]:
        if not any(str(c).strip() for c in row):
            continue
        rec = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            rec[h] = row[i] if i < len(row) else ""
        records.append(rec)
    return records


def get_next_id(ws):
    values = safe_get_all_values(ws)
    records = rows_to_records(values)
    if not records:
        return 1
    ids = []
    for r in records:
        try:
            ids.append(int(float(str(r.get("id", 0)))))
        except (TypeError, ValueError):
            pass
    return max(ids) + 1 if ids else 1


def _ids_equal(a, b):
    sa, sb = str(a).strip(), str(b).strip()
    if sa == sb:
        return True
    try:
        return int(float(sa)) == int(float(sb))
    except (TypeError, ValueError):
        return False


def find_row_by_id(ws, row_id):
    try:
        values = safe_get_all_values(ws)
        for i, row in enumerate(values):
            if i == 0 or not row:
                continue
            cell = str(row[0]).strip() if row else ""
            if cell and _ids_equal(cell, row_id):
                return i + 1
        return None
    except Exception:
        return None


def _cell_is_booked(value, booked_by=""):
    raw = str(value or "").strip().lower()
    if raw in ("1", "true", "да", "yes", "занята", "booked"):
        return True
    try:
        if int(float(raw)) == 1:
            return True
    except (TypeError, ValueError):
        pass
    if booked_by and str(booked_by).strip() and raw not in ("", "0", "false", "нет", "no", "свободна"):
        return True
    return False


def log_action(actor, action, details=""):
    try:
        ws = ensure_worksheet("action_log")
        new_id = get_next_id(ws)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([new_id, now, actor, action, details], value_input_option="USER_ENTERED")
    except Exception:
        pass


def add_topic(grade, subject, title, product, deadline=""):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    new_id = get_next_id(ws)
    ws.append_row([new_id, grade, subject, title, product, 0, "", "", deadline or ""], value_input_option="USER_ENTERED")
    try:
        log_action("учитель", "добавлена тема", f"id={new_id}, {grade}: {subject}: {title}")
    except Exception:
        pass
    get_topics_cached.clear()
    return new_id


def add_topics_bulk(rows):
    prepared = []
    for r in rows:
        title = str(r.get("title", "")).strip()
        subject = str(r.get("subject", "")).strip()
        if not title or not subject:
            continue
        prepared.append({"grade": str(r.get("grade", "8А")).strip() or "8А", "subject": subject, "title": title,
                         "product": str(r.get("product", "")).strip(), "deadline": str(r.get("deadline", "")).strip()})
    if not prepared:
        return 0
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    start_id = get_next_id(ws)
    batch = [[start_id + i, r["grade"], r["subject"], r["title"], r["product"], 0, "", "", r["deadline"]] for i, r in enumerate(prepared)]
    for i in range(0, len(batch), 50):
        chunk = batch[i:i + 50]
        for attempt in range(5):
            try:
                ws.append_rows(chunk, value_input_option="USER_ENTERED")
                break
            except Exception as e:
                if attempt == 4:
                    raise
                time.sleep(20 * (attempt + 1) if ("429" in str(e) or "Quota" in str(e)) else 3 * (attempt + 1))
        if i + 50 < len(batch):
            time.sleep(3)
    try:
        log_action("учитель", "массовое добавление тем", f"добавлено: {len(batch)}")
    except Exception:
        pass
    get_topics_cached.clear()
    return len(batch)


def _normalize_topic_row(r, row_index):
    title = str(r.get("title") or r.get("Тема") or r.get("тема") or "").strip()
    subject = str(r.get("subject") or r.get("Предмет") or r.get("предмет") or "").strip()
    if not title:
        return None
    raw_id = r.get("id") or r.get("ID") or ""
    try:
        tid = int(float(str(raw_id).strip()))
    except (TypeError, ValueError):
        tid = row_index
    if tid <= 0:
        tid = row_index
    raw_booked = str(r.get("is_booked", r.get("занята", "")) or "").strip().lower()
    if raw_booked in ("1", "true", "да", "yes", "занята", "booked"):
        is_booked = 1
    else:
        try:
            is_booked = 1 if int(float(raw_booked)) == 1 else 0
        except (TypeError, ValueError):
            is_booked = 0
    return {"id": tid, "grade": str(r.get("grade") or r.get("Класс") or r.get("класс") or "").strip(),
            "subject": subject, "title": title, "product": str(r.get("product") or r.get("Продукт") or "").strip(),
            "is_booked": is_booked, "booked_by": str(r.get("booked_by") or "").strip(),
            "booked_at": str(r.get("booked_at") or "").strip(), "deadline": str(r.get("deadline") or r.get("Дедлайн") or "").strip()}


@st.cache_data(ttl=20, show_spinner=False)
def get_topics_cached():
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    values = safe_get_all_values(ws)
    if not values:
        return []
    headers = [str(h).strip() for h in values[0]]
    while headers and headers[-1] == "":
        headers.pop()
    result = []
    for i, row in enumerate(values):
        if i == 0 or not any(str(c).strip() for c in row):
            continue
        rec = {h: (row[j] if j < len(row) else "") for j, h in enumerate(headers) if h}
        sheet_row = i + 1
        item = _normalize_topic_row(rec, sheet_row)
        if item:
            item["sheet_row"] = sheet_row
            result.append(item)
    return result


def get_topics(grade=None, only_free=False, search=None):
    result = []
    for item in get_topics_cached():
        if grade and str(item.get("grade", "")) != str(grade):
            continue
        if only_free and item["is_booked"] == 1:
            continue
        if search:
            s = search.lower()
            if s not in f"{item['title']} {item['subject']} {item['product']} {item['booked_by']}".lower():
                continue
        result.append(item)
    result.sort(key=lambda x: (x["subject"], x["title"]))
    return result


def get_student_booking(student_name):
    if not student_name:
        return None
    for t in get_topics_cached():
        if t["booked_by"] == student_name and t["is_booked"] == 1:
            return t
    return None


def book_topic(topic_id, student_name, sheet_row=None, expected_title=""):
    student_name = (student_name or "").strip()
    if not student_name:
        return False, "Укажите ФИО"
    existing = get_student_booking(student_name)
    if existing:
        return False, f"У вас уже забронирована тема: «{existing['title']}»"
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    values = safe_get_all_values(ws)
    if not values:
        return False, "Лист topics пуст"
    headers = [str(h).strip().lower() for h in values[0]]
    def col(*names, default=None):
        for n in names:
            if n in headers:
                return headers.index(n)
        return default
    i_id, i_title, i_booked, i_by, i_at = col("id", default=0), col("title", "тема", default=3), col("is_booked", "занята", default=5), col("booked_by", default=6), col("booked_at", default=7)
    row_num = None
    if sheet_row is not None:
        try:
            sr = int(sheet_row)
            if 2 <= sr <= len(values):
                row_num = sr
        except (TypeError, ValueError):
            pass
    if row_num is None and topic_id is not None:
        for i, row in enumerate(values):
            if i == 0:
                continue
            cell_id = row[i_id] if i_id < len(row) else ""
            if cell_id and _ids_equal(cell_id, topic_id):
                row_num = i + 1
                break
    if row_num is None:
        return False, "Тема не найдена. Нажмите 🔄 Обновить."
    row = list(values[row_num - 1])
    while len(row) < 9:
        row.append("")
    title = str(row[i_title] if i_title < len(row) else "").strip()
    flag = row[i_booked] if i_booked < len(row) else ""
    by = row[i_by] if i_by < len(row) else ""
    if expected_title and title and title.strip().lower() != str(expected_title).strip().lower():
        return False, f"На месте темы сейчас «{title}». Обновите список."
    if _cell_is_booked(flag, by):
        return False, f"Тема «{title}» уже занята" + (f" ({by})" if by else "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if i_by == i_booked + 1 and i_at == i_booked + 2:
        a1 = f"{rowcol_to_a1(row_num, i_booked + 1)}:{rowcol_to_a1(row_num, i_at + 1)}"
        ws.update(a1, [[1, student_name, now]], value_input_option="USER_ENTERED")
    else:
        ws.update(rowcol_to_a1(row_num, i_booked + 1), [[1]], value_input_option="USER_ENTERED")
        ws.update(rowcol_to_a1(row_num, i_by + 1), [[student_name]], value_input_option="USER_ENTERED")
        ws.update(rowcol_to_a1(row_num, i_at + 1), [[now]], value_input_option="USER_ENTERED")
    log_action(student_name, "бронь темы", f"row={row_num}, title={title}")
    get_topics_cached.clear()
    return True, f"Тема «{title}» забронирована!"


def unbook_topic(topic_id, actor="учитель", sheet_row=None, expected_title=""):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    values = safe_get_all_values(ws)
    if not values:
        return False, "Лист topics пуст"
    headers = [str(h).strip().lower() for h in values[0]]
    def col(*names, default=None):
        for n in names:
            if n in headers:
                return headers.index(n)
        return default
    i_id, i_title, i_booked, i_by, i_at = col("id", default=0), col("title", "тема", default=3), col("is_booked", "занята", default=5), col("booked_by", default=6), col("booked_at", default=7)
    row_num = None
    if sheet_row is not None:
        try:
            sr = int(sheet_row)
            if 2 <= sr <= len(values):
                row_num = sr
        except (TypeError, ValueError):
            pass
    if row_num is None and topic_id is not None:
        for i, row in enumerate(values):
            if i == 0:
                continue
            cell_id = row[i_id] if i_id < len(row) else ""
            if cell_id and _ids_equal(cell_id, topic_id):
                row_num = i + 1
                break
    if row_num is None:
        return False, f"Тема не найдена (id={topic_id})"
    row = list(values[row_num - 1])
    while len(row) < 9:
        row.append("")
    title = str(row[i_title] if i_title < len(row) else "").strip()
    was_by = row[i_by] if i_by < len(row) else ""
    if i_by == i_booked + 1 and i_at == i_booked + 2:
        a1 = f"{rowcol_to_a1(row_num, i_booked + 1)}:{rowcol_to_a1(row_num, i_at + 1)}"
        ws.update(a1, [[0, "", ""]], value_input_option="USER_ENTERED")
    else:
        ws.update(rowcol_to_a1(row_num, i_booked + 1), [[0]], value_input_option="USER_ENTERED")
        ws.update(rowcol_to_a1(row_num, i_by + 1), [[""]], value_input_option="USER_ENTERED")
        ws.update(rowcol_to_a1(row_num, i_at + 1), [[""]], value_input_option="USER_ENTERED")
    log_action(actor, "снята бронь", f"row={row_num}, title={title}, was={was_by}")
    get_topics_cached.clear()
    return True, f"Бронь снята с темы «{title or topic_id}»"


def delete_topic(topic_id):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_row_by_id(ws, topic_id)
    if row:
        ws.delete_rows(row)
        log_action("учитель", "удалена тема", f"topic_id={topic_id}")
        get_topics_cached.clear()


def update_topic(topic_id, grade, subject, title, product, deadline=""):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_row_by_id(ws, topic_id)
    if row:
        vals = ws.row_values(row)
        while len(vals) < 9:
            vals.append("")
        ws.update(f"B{row}:I{row}", [[grade, subject, title, product, vals[5], vals[6], vals[7], deadline or ""]], value_input_option="USER_ENTERED")
        log_action("учитель", "изменена тема", f"topic_id={topic_id}")
        get_topics_cached.clear()


def _guess_mime(filename, fallback="application/octet-stream"):
    name = (filename or "").lower()
    mapping = {
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".zip": "application/zip",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    for ext, mime in mapping.items():
        if name.endswith(ext):
            return mime
    return fallback


def upload_file_to_drive(uploaded_file, prefix="file"):
    _, drive_service = get_google_clients()
    folder_id = get_drive_folder_id().split("?")[0].strip().rstrip("/")
    if "/folders/" in folder_id:
        folder_id = folder_id.split("/folders/")[-1].split("/")[0].split("?")[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w\s\-.]", "", uploaded_file.name).strip().replace(" ", "_") or "file"
    filename = f"{prefix}_{timestamp}_{safe}"
    data = uploaded_file.getvalue()
    mime = uploaded_file.type or _guess_mime(uploaded_file.name)
    body = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
    try:
        file = drive_service.files().create(
            body=body, media_body=media, fields="id, webViewLink", supportsAllDrives=True
        ).execute(num_retries=2)
        return file.get("id"), file.get("webViewLink"), filename
    except Exception as e:
        raise RuntimeError(
            "Не удалось загрузить в Drive (часто нет квоты у сервис-аккаунта). "
            "Опубликуйте файл по ссылке: положите в папку Drive и используйте «по ссылке»."
        ) from e


def add_material(title, description, uploaded_file):
    if uploaded_file is None:
        raise ValueError("Файл не выбран")
    drive_id, link, fname = upload_file_to_drive(uploaded_file, prefix="material")
    ws = ensure_worksheet("materials")
    new_id = get_next_id(ws)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row(
        [new_id, title, description or "", uploaded_file.name, drive_id, link or "", now],
        value_input_option="USER_ENTERED",
    )
    log_action("учитель", "добавлен материал", title)
    return new_id


def add_material_by_link(title, description, link, filename=""):
    title = (title or "").strip()
    link = (link or "").strip()
    if not title:
        raise ValueError("Укажите название")
    if not link or not (link.startswith("http://") or link.startswith("https://")):
        raise ValueError("Укажите ссылку https://")
    ws = ensure_worksheet("materials")
    new_id = get_next_id(ws)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    fname = (filename or "").strip() or "файл по ссылке"
    ws.append_row([new_id, title, description or "", fname, "", link, now], value_input_option="USER_ENTERED")
    log_action("учитель", "материал по ссылке", title)
    return new_id


def get_materials():
    try:
        ws = ensure_worksheet("materials")
        records = rows_to_records(safe_get_all_values(ws))
    except Exception:
        return []
    result = []
    for r in records:
        try:
            mid = int(r.get("id", 0))
        except (TypeError, ValueError):
            continue
        if mid <= 0:
            continue
        result.append({"id": mid, "title": str(r.get("title", "")), "description": str(r.get("description", "") or ""),
                       "filename": str(r.get("filename", "")), "drive_file_id": str(r.get("drive_file_id", "")),
                       "drive_link": str(r.get("drive_link", "")), "uploaded_at": str(r.get("uploaded_at", ""))})
    result.sort(key=lambda x: x["uploaded_at"], reverse=True)
    return result


def delete_material(mat_id):
    ws = ensure_worksheet("materials")
    row = find_row_by_id(ws, mat_id)
    if row:
        ws.delete_rows(row)
        log_action("учитель", "удалён материал", f"id={mat_id}")


def _find_submission_row(ws, topic_id, student_name):
    values = safe_get_all_values(ws)
    for i, row in enumerate(values):
        if i == 0 or len(row) < 3:
            continue
        if str(row[1]).strip() == str(topic_id) and str(row[2]).strip() == str(student_name):
            return i + 1, row
    return None, None


def submit_work(topic_id, student_name, student_class, uploaded_file):
    if uploaded_file is None:
        return False, "Файл не выбран"
    try:
        drive_id, link, _ = upload_file_to_drive(uploaded_file, prefix=f"work_{student_name}")
    except Exception as e:
        return False, f"Ошибка загрузки в Drive: {e}"
    ws = ensure_worksheet("submissions")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    row_num, old = _find_submission_row(ws, topic_id, student_name)
    if row_num and old:
        old_name = old[4] if len(old) > 4 else ""
        old_link = old[6] if len(old) > 6 else ""
        old_versions = old[12] if len(old) > 12 else ""
        old_history = old[11] if len(old) > 11 else ""
        version_entry = f"{now} | {old_name} | {old_link}".strip(" |")
        versions = f"{version_entry};;{old_versions}".strip("; ") if (old_link or old_name) else old_versions
        history = (old_history + f"\n{now} — пересдано (на проверке)").strip()
        ws.update(
            f"B{row_num}:M{row_num}",
            [[topic_id, student_name, student_class, uploaded_file.name, drive_id, link or "",
              "на проверке", "", old[9] if len(old) > 9 else now, now, history, versions]],
            value_input_option="USER_ENTERED",
        )
        log_action(student_name, "пересдача работы", f"topic_id={topic_id}")
        return True, "Работа пересдана."
    new_id = get_next_id(ws)
    history = f"{now} — сдано (на проверке)"
    ws.append_row(
        [new_id, topic_id, student_name, student_class, uploaded_file.name, drive_id, link or "",
         "на проверке", "", now, now, history, ""],
        value_input_option="USER_ENTERED",
    )
    log_action(student_name, "сдана работа", f"topic_id={topic_id}")
    return True, "Работа успешно отправлена!"


def get_submissions(status=None, search=None):
    try:
        ws = ensure_worksheet("submissions")
        records = rows_to_records(safe_get_all_values(ws))
    except Exception as e:
        st.warning(f"Не удалось загрузить работы: {e}")
        return []
    topics_map = {t["id"]: t for t in get_topics_cached()}
    result = []
    for r in records:
        try:
            sid = int(r.get("id", 0))
            tid = int(r.get("topic_id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if sid <= 0:
            continue
        topic = topics_map.get(tid, {})
        item = {"id": sid, "topic_id": tid, "student_name": str(r.get("student_name", "")), "student_class": str(r.get("student_class", "")),
                "filename": str(r.get("filename", "")), "drive_file_id": str(r.get("drive_file_id", "")), "drive_link": str(r.get("drive_link", "")),
                "status": str(r.get("status", "на проверке") or "на проверке"), "teacher_comment": str(r.get("teacher_comment", "") or ""),
                "submitted_at": str(r.get("submitted_at", "")), "updated_at": str(r.get("updated_at", "")),
                "status_history": str(r.get("status_history", "") or ""), "versions": str(r.get("versions", "") or ""),
                "title": topic.get("title", "—"), "subject": topic.get("subject", "—"), "grade": topic.get("grade", "—"), "product": topic.get("product", "")}
        if status and item["status"] != status:
            continue
        if search:
            s = search.lower()
            if s not in f"{item['student_name']} {item['student_class']} {item['title']} {item['subject']}".lower():
                continue
        result.append(item)
    result.sort(key=lambda x: x["submitted_at"], reverse=True)
    return result


def update_submission_status(sub_id, status, comment=""):
    ws = ensure_worksheet("submissions")
    row = find_row_by_id(ws, sub_id)
    if row:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        vals = ws.row_values(row)
        while len(vals) < 13:
            vals.append("")
        submitted = vals[9] if vals[9] else now
        history = vals[11] if len(vals) > 11 else ""
        note = f" — {comment[:80]}" if comment else ""
        history = (history + f"\n{now} — {status}{note}").strip()
        ws.update(f"H{row}:L{row}", [[status, comment, submitted, now, history]], value_input_option="USER_ENTERED")
        log_action("учитель", f"статус → {status}", f"submission_id={sub_id}")


def get_student_submissions(student_name):
    return [s for s in get_submissions() if s["student_name"] == student_name]


def get_action_log(limit=100):
    try:
        ws = ensure_worksheet("action_log")
        records = rows_to_records(safe_get_all_values(ws))
    except Exception:
        return []
    result = [{"id": r.get("id", ""), "timestamp": str(r.get("timestamp", "")), "actor": str(r.get("actor", "")),
               "action": str(r.get("action", "")), "details": str(r.get("details", ""))} for r in records]
    result.sort(key=lambda x: x["timestamp"], reverse=True)
    return result[:limit]


def add_question(student_name, student_class, question, topic_title=""):
    student_name = (student_name or "").strip()
    question = (question or "").strip()
    if not student_name:
        return False, "Укажите ФИО"
    if not question or len(question) < 5:
        return False, "Напишите вопрос"
    ws = ensure_worksheet("questions")
    new_id = get_next_id(ws)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([new_id, student_name, student_class or "", topic_title or "", question, "", "новый", now, ""], value_input_option="USER_ENTERED")
    log_action(student_name, "вопрос учителю", question[:80])
    return True, "Вопрос отправлен учителю"


def get_questions(status=None, search=None, student_name=None):
    try:
        ws = ensure_worksheet("questions")
        records = rows_to_records(safe_get_all_values(ws))
    except Exception:
        return []
    result = []
    for r in records:
        try:
            qid = int(float(str(r.get("id", 0) or 0)))
        except (TypeError, ValueError):
            continue
        if qid <= 0:
            continue
        item = {"id": qid, "student_name": str(r.get("student_name", "") or ""), "student_class": str(r.get("student_class", "") or ""),
                "topic_title": str(r.get("topic_title", "") or ""), "question": str(r.get("question", "") or ""),
                "answer": str(r.get("answer", "") or ""), "status": str(r.get("status", "новый") or "новый"),
                "created_at": str(r.get("created_at", "") or ""), "answered_at": str(r.get("answered_at", "") or "")}
        if student_name and item["student_name"] != student_name:
            continue
        if status and item["status"] != status:
            continue
        if search:
            s = search.lower()
            if s not in f"{item['student_name']} {item['student_class']} {item['question']} {item['topic_title']}".lower():
                continue
        result.append(item)
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result


def answer_question(question_id, answer):
    answer = (answer or "").strip()
    if not answer:
        return False, "Напишите ответ"
    ws = ensure_worksheet("questions")
    row = find_row_by_id(ws, question_id)
    if not row:
        return False, "Вопрос не найден"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.update(f"F{row}:G{row}", [[answer, "отвечен"]], value_input_option="USER_ENTERED")
    ws.update(f"I{row}", [[now]], value_input_option="USER_ENTERED")
    log_action("учитель", "ответ на вопрос", f"id={question_id}")
    return True, "Ответ сохранён"


def mark_question_status(question_id, status):
    status = (status or "").strip()
    if status not in ("новый", "в работе", "отвечен", "закрыт"):
        return False, "Неизвестный статус"
    ws = ensure_worksheet("questions")
    row = find_row_by_id(ws, question_id)
    if not row:
        return False, "Вопрос не найден"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.update(f"G{row}", [[status]], value_input_option="USER_ENTERED")
    if status == "отвечен":
        ws.update(f"I{row}", [[now]], value_input_option="USER_ENTERED")
    log_action("учитель", f"статус вопроса → {status}", f"id={question_id}")
    return True, f"Статус: {status}"


def add_announcement(title, text):
    title = (title or "").strip()
    text = (text or "").strip()
    if not title:
        return False, "Укажите заголовок"
    if not text:
        return False, "Напишите текст объявления"
    ws = ensure_worksheet("announcements")
    new_id = get_next_id(ws)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([new_id, title, text, 1, now, now], value_input_option="USER_ENTERED")
    log_action("учитель", "объявление", title)
    return True, "Объявление опубликовано"


def get_announcements(only_active=True):
    try:
        ws = ensure_worksheet("announcements")
        records = rows_to_records(safe_get_all_values(ws))
    except Exception:
        return []
    result = []
    for r in records:
        try:
            aid = int(float(str(r.get("id", 0) or 0)))
        except (TypeError, ValueError):
            continue
        if aid <= 0:
            continue
        raw = str(r.get("is_active", "1") or "1").strip().lower()
        is_active = raw in ("1", "true", "да", "yes", "active")
        try:
            if int(float(raw)) == 1:
                is_active = True
        except (TypeError, ValueError):
            pass
        if only_active and not is_active:
            continue
        result.append({"id": aid, "title": str(r.get("title", "") or ""), "text": str(r.get("text", "") or ""),
                       "is_active": 1 if is_active else 0, "created_at": str(r.get("created_at", "") or ""),
                       "updated_at": str(r.get("updated_at", "") or "")})
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result


def update_announcement(ann_id, title, text, is_active=True):
    title = (title or "").strip()
    text = (text or "").strip()
    if not title or not text:
        return False, "Заголовок и текст обязательны"
    ws = ensure_worksheet("announcements")
    row = find_row_by_id(ws, ann_id)
    if not row:
        return False, "Объявление не найдено"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    vals = ws.row_values(row)
    created = vals[4] if len(vals) > 4 and vals[4] else now
    ws.update(f"B{row}:F{row}", [[title, text, 1 if is_active else 0, created, now]], value_input_option="USER_ENTERED")
    log_action("учитель", "изменено объявление", title)
    return True, "Сохранено"


def set_announcement_active(ann_id, is_active):
    ws = ensure_worksheet("announcements")
    row = find_row_by_id(ws, ann_id)
    if not row:
        return False, "Не найдено"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.update(f"D{row}", [[1 if is_active else 0]], value_input_option="USER_ENTERED")
    ws.update(f"F{row}", [[now]], value_input_option="USER_ENTERED")
    log_action("учитель", "объявление " + ("вкл" if is_active else "выкл"), f"id={ann_id}")
    return True, "Ок"


def delete_announcement(ann_id):
    ws = ensure_worksheet("announcements")
    row = find_row_by_id(ws, ann_id)
    if row:
        ws.delete_rows(row)
        log_action("учитель", "удалено объявление", f"id={ann_id}")
        return True, "Удалено"
    return False, "Не найдено"


def topics_to_csv(topics):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "grade", "subject", "title", "product", "is_booked", "booked_by", "booked_at", "deadline"])
    for t in topics:
        w.writerow([t["id"], t["grade"], t["subject"], t["title"], t["product"], t["is_booked"], t["booked_by"], t["booked_at"], t["deadline"]])
    return buf.getvalue()


def submissions_to_csv(subs):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "student_name", "student_class", "grade", "subject", "title", "status", "submitted_at", "teacher_comment", "drive_link"])
    for s in subs:
        w.writerow([s["id"], s["student_name"], s["student_class"], s["grade"], s["subject"], s["title"], s["status"], s["submitted_at"], s["teacher_comment"], s["drive_link"]])
    return buf.getvalue()
