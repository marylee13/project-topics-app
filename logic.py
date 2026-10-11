import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
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
                    "drive_file_id", "drive_link", "status", "teacher_comment", "submitted_at", "updated_at"],
    "materials": ["id", "title", "description", "filename", "drive_file_id", "drive_link", "uploaded_at"],
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


def get_or_create_worksheet(spreadsheet, title, headers):
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=2000, cols=max(len(headers), 12))
        ws.update("A1", [headers])
        return ws


@st.cache_resource
def init_sheets():
    ss = get_spreadsheet()
    existing_titles = {ws.title for ws in ss.worksheets()}
    for name, headers in HEADERS.items():
        if name not in existing_titles:
            ws = ss.add_worksheet(title=name, rows=2000, cols=max(len(headers), 12))
            ws.update("A1", [headers])
            time.sleep(0.5)
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


def find_row_by_id(ws, row_id):
    try:
        values = safe_get_all_values(ws)
        for i, row in enumerate(values):
            if i == 0:
                continue
            if row and str(row[0]).strip() == str(row_id):
                return i + 1
        return None
    except Exception:
        return None


def log_action(actor, action, details=""):
    try:
        ss = get_spreadsheet()
        ws = ss.worksheet("action_log")
        new_id = get_next_id(ws)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([new_id, now, actor, action, details], value_input_option="USER_ENTERED")
    except Exception:
        pass


def add_topic(grade, subject, title, product, deadline=""):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    new_id = get_next_id(ws)
    ws.append_row(
        [new_id, grade, subject, title, product, 0, "", "", deadline or ""],
        value_input_option="USER_ENTERED",
    )
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
        prepared.append({
            "grade": str(r.get("grade", "8А")).strip() or "8А",
            "subject": subject,
            "title": title,
            "product": str(r.get("product", "")).strip(),
            "deadline": str(r.get("deadline", "")).strip(),
        })
    if not prepared:
        return 0

    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    start_id = get_next_id(ws)

    batch = []
    for i, r in enumerate(prepared):
        batch.append([
            start_id + i, r["grade"], r["subject"], r["title"], r["product"],
            0, "", "", r["deadline"],
        ])

    chunk_size = 50
    for i in range(0, len(batch), chunk_size):
        chunk = batch[i:i + chunk_size]
        for attempt in range(5):
            try:
                ws.append_rows(chunk, value_input_option="USER_ENTERED")
                break
            except Exception as e:
                if attempt == 4:
                    raise
                wait = 20 * (attempt + 1) if ("429" in str(e) or "Quota" in str(e)) else 3 * (attempt + 1)
                time.sleep(wait)
        if i + chunk_size < len(batch):
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

    return {
        "id": tid,
        "grade": str(r.get("grade") or r.get("Класс") or r.get("класс") or "").strip(),
        "subject": subject,
        "title": title,
        "product": str(r.get("product") or r.get("Продукт") or "").strip(),
        "is_booked": is_booked,
        "booked_by": str(r.get("booked_by") or "").strip(),
        "booked_at": str(r.get("booked_at") or "").strip(),
        "deadline": str(r.get("deadline") or r.get("Дедлайн") or "").strip(),
    }


@st.cache_data(ttl=20, show_spinner=False)
def get_topics_cached():
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    values = safe_get_all_values(ws)
    records = rows_to_records(values)
    result = []
    for i, r in enumerate(records, start=2):
        item = _normalize_topic_row(r, i)
        if item:
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
            blob = f"{item['title']} {item['subject']} {item['product']} {item['booked_by']}".lower()
            if s not in blob:
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


def book_topic(topic_id, student_name):
    existing = get_student_booking(student_name)
    if existing:
        return False, f"У вас уже забронирована тема: «{existing['title']}»"
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_row_by_id(ws, topic_id)
    if not row:
        return False, "Тема не найдена"
    vals = ws.row_values(row)
    is_booked = vals[5] if len(vals) > 5 else "0"
    if str(is_booked).strip() in ("1", "true", "TRUE", "да"):
        return False, "Тема уже занята"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.update(f"F{row}:H{row}", [[1, student_name, now]], value_input_option="USER_ENTERED")
    log_action(student_name, "бронь темы", f"topic_id={topic_id}")
    get_topics_cached.clear()
    return True, "Тема забронирована!"


def unbook_topic(topic_id, actor="учитель"):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_row_by_id(ws, topic_id)
    if row:
        ws.update(f"F{row}:H{row}", [[0, "", ""]], value_input_option="USER_ENTERED")
        log_action(actor, "снята бронь", f"topic_id={topic_id}")
        get_topics_cached.clear()


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
        ws.update(
            f"B{row}:I{row}",
            [[grade, subject, title, product, vals[5], vals[6], vals[7], deadline or ""]],
            value_input_option="USER_ENTERED",
        )
        log_action("учитель", "изменена тема", f"topic_id={topic_id}")
        get_topics_cached.clear()


def upload_file_to_drive(uploaded_file, prefix="file"):
    _, drive_service = get_google_clients()
    folder_id = get_drive_folder_id()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w\s\-.]", "", uploaded_file.name).strip().replace(" ", "_")
    filename = f"{prefix}_{timestamp}_{safe}"
    media = MediaIoBaseUpload(
        io.BytesIO(uploaded_file.getvalue()),
        mimetype=uploaded_file.type or "application/octet-stream",
        resumable=True,
    )
    file = drive_service.files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=media,
        fields="id, webViewLink",
    ).execute()
    return file.get("id"), file.get("webViewLink"), filename


def add_material(title, description, uploaded_file):
    drive_id, link, fname = upload_file_to_drive(uploaded_file, prefix="material")
    ss = get_spreadsheet()
    ws = ss.worksheet("materials")
    new_id = get_next_id(ws)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([new_id, title, description or "", uploaded_file.name, drive_id, link or "", now], value_input_option="USER_ENTERED")
    log_action("учитель", "добавлен материал", title)
    return new_id


def get_materials():
    try:
        ss = get_spreadsheet()
        ws = ss.worksheet("materials")
        values = safe_get_all_values(ws)
        records = rows_to_records(values)
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
        result.append({
            "id": mid,
            "title": str(r.get("title", "")),
            "description": str(r.get("description", "") or ""),
            "filename": str(r.get("filename", "")),
            "drive_file_id": str(r.get("drive_file_id", "")),
            "drive_link": str(r.get("drive_link", "")),
            "uploaded_at": str(r.get("uploaded_at", "")),
        })
    result.sort(key=lambda x: x["uploaded_at"], reverse=True)
    return result


def delete_material(mat_id):
    ss = get_spreadsheet()
    ws = ss.worksheet("materials")
    row = find_row_by_id(ws, mat_id)
    if row:
        ws.delete_rows(row)
        log_action("учитель", "удалён материал", f"id={mat_id}")


def submit_work(topic_id, student_name, student_class, uploaded_file):
    if uploaded_file is None:
        return False, "Файл не выбран"
    try:
        drive_id, link, _ = upload_file_to_drive(uploaded_file, prefix=f"work_{student_name}")
    except Exception as e:
        return False, f"Ошибка загрузки в Drive: {e}"
    ss = get_spreadsheet()
    ws = ss.worksheet("submissions")
    new_id = get_next_id(ws)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([
        new_id, topic_id, student_name, student_class,
        uploaded_file.name, drive_id, link or "",
        "на проверке", "", now, now,
    ], value_input_option="USER_ENTERED")
    log_action(student_name, "сдана работа", f"topic_id={topic_id}, file={uploaded_file.name}")
    return True, "Работа успешно отправлена!"


def get_submissions(status=None, search=None):
    try:
        ss = get_spreadsheet()
        ws = ss.worksheet("submissions")
        values = safe_get_all_values(ws)
        records = rows_to_records(values)
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
        item = {
            "id": sid,
            "topic_id": tid,
            "student_name": str(r.get("student_name", "")),
            "student_class": str(r.get("student_class", "")),
            "filename": str(r.get("filename", "")),
            "drive_file_id": str(r.get("drive_file_id", "")),
            "drive_link": str(r.get("drive_link", "")),
            "status": str(r.get("status", "на проверке") or "на проверке"),
            "teacher_comment": str(r.get("teacher_comment", "") or ""),
            "submitted_at": str(r.get("submitted_at", "")),
            "updated_at": str(r.get("updated_at", "")),
            "title": topic.get("title", "—"),
            "subject": topic.get("subject", "—"),
            "grade": topic.get("grade", "—"),
        }
        if status and item["status"] != status:
            continue
        if search:
            s = search.lower()
            blob = f"{item['student_name']} {item['student_class']} {item['title']} {item['subject']}".lower()
            if s not in blob:
                continue
        result.append(item)
    result.sort(key=lambda x: x["submitted_at"], reverse=True)
    return result


def update_submission_status(sub_id, status, comment=""):
    ss = get_spreadsheet()
    ws = ss.worksheet("submissions")
    row = find_row_by_id(ws, sub_id)
    if row:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        vals = ws.row_values(row)
        submitted = vals[9] if len(vals) > 9 else ""
        ws.update(f"H{row}:K{row}", [[status, comment, submitted, now]], value_input_option="USER_ENTERED")
        log_action("учитель", f"статус → {status}", f"submission_id={sub_id}")


def get_student_submissions(student_name):
    return [s for s in get_submissions() if s["student_name"] == student_name]


def get_action_log(limit=100):
    try:
        ss = get_spreadsheet()
        ws = ss.worksheet("action_log")
        values = safe_get_all_values(ws)
        records = rows_to_records(values)
    except Exception:
        return []
    result = []
    for r in records:
        result.append({
            "id": r.get("id", ""),
            "timestamp": str(r.get("timestamp", "")),
            "actor": str(r.get("actor", "")),
            "action": str(r.get("action", "")),
            "details": str(r.get("details", "")),
        })
    result.sort(key=lambda x: x["timestamp"], reverse=True)
    return result[:limit]


def topics_to_csv(topics):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "grade", "subject", "title", "product", "is_booked", "booked_by", "booked_at", "deadline"])
    for t in topics:
        w.writerow([t["id"], t["grade"], t["subject"], t["title"], t["product"],
                    t["is_booked"], t["booked_by"], t["booked_at"], t["deadline"]])
    return buf.getvalue()


def submissions_to_csv(subs):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "student_name", "student_class", "grade", "subject", "title",
                "status", "submitted_at", "teacher_comment", "drive_link"])
    for s in subs:
        w.writerow([s["id"], s["student_name"], s["student_class"], s["grade"], s["subject"],
                    s["title"], s["status"], s["submitted_at"], s["teacher_comment"], s["drive_link"]])
    return buf.getvalue()
