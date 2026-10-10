import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
import io
import re
import csv

# ==================== НАСТРОЙКИ ====================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
TEACHER_PASSWORD = "marylee_13"

# ==================== GOOGLE ====================
@st.cache_resource
def get_google_clients():
    try:
        creds_info = st.secrets["gcp_service_account"]
        credentials = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        gc = gspread.authorize(credentials)
        drive_service = build("drive", "v3", credentials=credentials)
        return gc, drive_service
    except Exception as e:
        st.error("Ошибка подключения к Google. Проверьте Secrets.")
        st.exception(e)
        st.stop()


def get_spreadsheet():
    gc, _ = get_google_clients()
    return gc.open_by_key(st.secrets["SPREADSHEET_ID"])


def get_drive_folder_id():
    return st.secrets["DRIVE_FOLDER_ID"]


def get_or_create_worksheet(spreadsheet, title, headers):
    try:
        ws = spreadsheet.worksheet(title)
        existing = ws.row_values(1)
        if not existing:
            ws.append_row(headers)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=2000, cols=max(len(headers), 12))
        ws.append_row(headers)
    return ws


def init_sheets():
    ss = get_spreadsheet()
    get_or_create_worksheet(
        ss, "topics",
        ["id", "grade", "subject", "title", "product", "is_booked", "booked_by", "booked_at", "deadline"],
    )
    get_or_create_worksheet(
        ss, "submissions",
        ["id", "topic_id", "student_name", "student_class", "filename",
         "drive_file_id", "drive_link", "status", "teacher_comment", "submitted_at", "updated_at"],
    )
    get_or_create_worksheet(
        ss, "materials",
        ["id", "title", "description", "filename", "drive_file_id", "drive_link", "uploaded_at"],
    )
    get_or_create_worksheet(
        ss, "action_log",
        ["id", "timestamp", "actor", "action", "details"],
    )
    return ss


def get_next_id(ws):
    records = ws.get_all_records()
    if not records:
        return 1
    ids = []
    for r in records:
        try:
            ids.append(int(r.get("id", 0)))
        except (TypeError, ValueError):
            pass
    return max(ids) + 1 if ids else 1


def find_row_by_id(ws, row_id):
    try:
        cell = ws.find(str(row_id), in_column=1)
        return cell.row if cell else None
    except Exception:
        return None


def log_action(actor, action, details=""):
    try:
        ss = get_spreadsheet()
        ws = ss.worksheet("action_log")
        new_id = get_next_id(ws)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([new_id, now, actor, action, details])
    except Exception:
        pass


def add_topic(grade, subject, title, product, deadline=""):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    new_id = get_next_id(ws)
    ws.append_row([new_id, grade, subject, title, product, 0, "", "", deadline or ""])
    log_action("учитель", "добавлена тема", f"id={new_id}, {grade} кл., {subject}: {title}")
    return new_id


def add_topics_bulk(rows):
    count = 0
    for r in rows:
        if r.get("title") and r.get("subject"):
            add_topic(
                str(r.get("grade", "8")).strip(),
                str(r["subject"]).strip(),
                str(r["title"]).strip(),
                str(r.get("product", "")).strip(),
                str(r.get("deadline", "")).strip(),
            )
            count += 1
    return count


def get_topics(grade=None, only_free=False, search=None):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    records = ws.get_all_records()
    result = []
    for r in records:
        try:
            tid = int(r["id"])
        except (TypeError, ValueError, KeyError):
            continue
        if grade and str(r.get("grade", "")) != str(grade):
            continue
        is_booked = int(r.get("is_booked", 0) or 0)
        if only_free and is_booked == 1:
            continue
        item = {
            "id": tid,
            "grade": str(r.get("grade", "")),
            "subject": str(r.get("subject", "")),
            "title": str(r.get("title", "")),
            "product": str(r.get("product", "")),
            "is_booked": is_booked,
            "booked_by": str(r.get("booked_by", "") or ""),
            "booked_at": str(r.get("booked_at", "") or ""),
            "deadline": str(r.get("deadline", "") or ""),
        }
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
    for t in get_topics():
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
    val = ws.cell(row, 6).value
    if str(val) == "1":
        return False, "Тема уже занята"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.update(f"F{row}:H{row}", [[1, student_name, now]])
    log_action(student_name, "бронь темы", f"topic_id={topic_id}")
    return True, "Тема забронирована!"


def unbook_topic(topic_id, actor="учитель"):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_row_by_id(ws, topic_id)
    if row:
        ws.update(f"F{row}:H{row}", [[0, "", ""]])
        log_action(actor, "снята бронь", f"topic_id={topic_id}")


def delete_topic(topic_id):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_row_by_id(ws, topic_id)
    if row:
        ws.delete_rows(row)
        log_action("учитель", "удалена тема", f"topic_id={topic_id}")


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
        )
        log_action("учитель", "изменена тема", f"topic_id={topic_id}")


def upload_file_to_drive(uploaded_file, prefix="file"):
    _, drive_service = get_google_clients()
    folder_id = get_drive_folder_id()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w\s\-\.]", "", uploaded_file.name).strip().replace(" ", "_")
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
    ws.append_row([new_id, title, description or "", uploaded_file.name, drive_id, link or "", now])
    log_action("учитель", "добавлен материал", title)
    return new_id


def get_materials():
    ss = get_spreadsheet()
    ws = ss.worksheet("materials")
    records = ws.get_all_records()
    result = []
    for r in records:
        try:
            mid = int(r["id"])
        except (TypeError, ValueError, KeyError):
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
    ])
    log_action(student_name, "сдана работа", f"topic_id={topic_id}, file={uploaded_file.name}")
    return True, "Работа успешно отправлена!"


def get_submissions(status=None, search=None):
    ss = get_spreadsheet()
    ws = ss.worksheet("submissions")
    records = ws.get_all_records()
    topics_map = {t["id"]: t for t in get_topics()}
    result = []
    for r in records:
        try:
            sid = int(r["id"])
            tid = int(r.get("topic_id", 0) or 0)
        except (TypeError, ValueError):
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
            "status": str(r.get("status", "на проверке")),
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
        submitted = ws.cell(row, 10).value or ""
        ws.update(f"H{row}:K{row}", [[status, comment, submitted, now]])
        log_action("учитель", f"статус → {status}", f"submission_id={sub_id}")


def get_student_submissions(student_name):
    return [s for s in get_submissions() if s["student_name"] == student_name]


def get_action_log(limit=100):
    ss = get_spreadsheet()
    ws = ss.worksheet("action_log")
    records = ws.get_all_records()
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
