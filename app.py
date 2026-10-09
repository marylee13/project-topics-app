import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
import io
import re

# ==================== НАСТРОЙКИ ====================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

TEACHER_PASSWORD = "marylee_13"  # Смените пароль!

# ==================== ПОДКЛЮЧЕНИЕ К GOOGLE ====================
@st.cache_resource
def get_google_clients():
    """Создаёт клиенты Google Sheets и Drive из secrets."""
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
    sheet_id = st.secrets["SPREADSHEET_ID"]
    return gc.open_by_key(sheet_id)


def get_drive_folder_id():
    return st.secrets["DRIVE_FOLDER_ID"]


def get_or_create_worksheet(spreadsheet, title, headers):
    """Получает лист или создаёт его с заголовками."""
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws


def init_sheets():
    """Инициализирует нужные листы."""
    ss = get_spreadsheet()
    topics_headers = ["id", "grade", "subject", "title", "product", "is_booked", "booked_by", "booked_at"]
    subs_headers = ["id", "topic_id", "student_name", "student_class", "filename",
                    "drive_file_id", "drive_link", "status", "teacher_comment",
                    "submitted_at", "updated_at"]
    get_or_create_worksheet(ss, "topics", topics_headers)
    get_or_create_worksheet(ss, "submissions", subs_headers)
    return ss


# ==================== ТЕМЫ ====================
def get_next_id(ws):
    records = ws.get_all_records()
    if not records:
        return 1
    ids = [int(r["id"]) for r in records if str(r.get("id", "")).isdigit()]
    return max(ids) + 1 if ids else 1


def add_topic(grade, subject, title, product):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    new_id = get_next_id(ws)
    ws.append_row([new_id, grade, subject, title, product, 0, "", ""])
    return new_id


def get_topics(grade=None, only_free=False):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    records = ws.get_all_records()
    result = []
    for r in records:
        if grade and str(r.get("grade", "")) != str(grade):
            continue
        is_booked = int(r.get("is_booked", 0) or 0)
        if only_free and is_booked == 1:
            continue
        result.append({
            "id": int(r["id"]),
            "grade": str(r.get("grade", "")),
            "subject": str(r.get("subject", "")),
            "title": str(r.get("title", "")),
            "product": str(r.get("product", "")),
            "is_booked": is_booked,
            "booked_by": str(r.get("booked_by", "") or ""),
            "booked_at": str(r.get("booked_at", "") or ""),
        })
    result.sort(key=lambda x: (x["subject"], x["title"]))
    return result


def find_topic_row(ws, topic_id):
    cell = ws.find(str(topic_id), in_column=1)
    return cell.row if cell else None


def book_topic(topic_id, student_name):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_topic_row(ws, topic_id)
    if not row:
        return False
    val = ws.cell(row, 6).value
    if str(val) == "1":
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.update(f"F{row}:H{row}", [[1, student_name, now]])
    return True


def unbook_topic(topic_id):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_topic_row(ws, topic_id)
    if row:
        ws.update(f"F{row}:H{row}", [[0, "", ""]])


def delete_topic(topic_id):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_topic_row(ws, topic_id)
    if row:
        ws.delete_rows(row)


def update_topic(topic_id, grade, subject, title, product):
    ss = get_spreadsheet()
    ws = ss.worksheet("topics")
    row = find_topic_row(ws, topic_id)
    if row:
        booked = ws.row_values(row)[5:8]
        while len(booked) < 3:
            booked.append("")
        ws.update(f"B{row}:H{row}", [[grade, subject, title, product, booked[0], booked[1], booked[2]]])


# ==================== РАБОТЫ + GOOGLE DRIVE ====================
def upload_to_drive(uploaded_file, student_name, topic_id):
    _, drive_service = get_google_clients()
    folder_id = get_drive_folder_id()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w\s\-]", "", student_name).strip().replace(" ", "_")
    ext = uploaded_file.name.split(".")[-1] if "." in uploaded_file.name else "bin"
    filename = f"{timestamp}_{safe_name}_{topic_id}.{ext}"

    file_metadata = {
        "name": filename,
        "parents": [folder_id]
    }
    media = MediaIoBaseUpload(
        io.BytesIO(uploaded_file.getvalue()),
        mimetype=uploaded_file.type or "application/octet-stream",
        resumable=True
    )
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink"
    ).execute()
    return file.get("id"), file.get("webViewLink")


def submit_work(topic_id, student_name, student_class, uploaded_file):
    if uploaded_file is None:
        return False, "Файл не выбран"

    try:
        drive_file_id, drive_link = upload_to_drive(uploaded_file, student_name, topic_id)
    except Exception as e:
        return False, f"Ошибка загрузки в Google Drive: {e}"

    ss = get_spreadsheet()
    ws = ss.worksheet("submissions")
    new_id = get_next_id(ws)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    ws.append_row([
        new_id,
        topic_id,
        student_name,
        student_class,
        uploaded_file.name,
        drive_file_id,
        drive_link or "",
        "на проверке",
        "",
        now,
        now
    ])
    return True, "Работа успешно отправлена!"


def get_submissions(status=None):
    ss = get_spreadsheet()
    ws = ss.worksheet("submissions")
    records = ws.get_all_records()
    topics = {t["id"]: t for t in get_topics()}

    result = []
    for r in records:
        tid = int(r.get("topic_id", 0) or 0)
        topic = topics.get(tid, {})
        item = {
            "id": int(r["id"]),
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
        result.append(item)
    result.sort(key=lambda x: x["submitted_at"], reverse=True)
    return result


def update_submission_status(sub_id, status, comment=""):
    ss = get_spreadsheet()
    ws = ss.worksheet("submissions")
    row = find_topic_row(ws, sub_id)
    if row:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        ws.update(f"H{row}:K{row}", [[status, comment, ws.cell(row, 10).value, now]])


def get_student_submissions(student_name):
    all_subs = get_submissions()
    return [s for s in all_subs if s["student_name"] == student_name]


# ==================== ИНТЕРФЕЙС ====================
st.set_page_config(
    page_title="Темы проектов — бронирование",
    page_icon="📚",
    layout="wide"
)

# Проверяем secrets
if "gcp_service_account" not in st.secrets or "SPREADSHEET_ID" not in st.secrets or "DRIVE_FOLDER_ID" not in st.secrets:
    st.error("Не настроены Google Secrets. Следуйте инструкции в README.")
    st.stop()

init_sheets()

st.sidebar.title("📚 Темы проектов")
role = st.sidebar.radio("Кто вы?", ["Ученик", "Учитель"])

# -------------------- УЧЕНИК --------------------
if role == "Ученик":
    st.title("Бронирование темы проекта")
    st.caption("Выберите класс → посмотрите свободные темы → забронируйте → сдайте работу")

    tab1, tab2, tab3 = st.tabs(["1. Выбрать тему", "2. Сдать работу", "3. Мои работы"])

    with tab1:
        st.subheader("Свободные темы")
        grade = st.selectbox("Ваш класс", ["5", "6", "7", "8", "9", "10", "11"], index=3)

        topics = get_topics(grade=grade, only_free=True)

        if not topics:
            st.info("Сейчас нет свободных тем для этого класса. Обратитесь к учителю.")
        else:
            subjects = {}
            for t in topics:
                subj = t["subject"]
                subjects.setdefault(subj, []).append(t)

            for subj, items in subjects.items():
                with st.expander(f"📌 {subj} ({len(items)})", expanded=False):
                    for t in items:
                        col1, col2 = st.columns([4, 1])
                        with col1:
                            st.markdown(f"**{t['title']}**")
                            if t["product"]:
                                st.caption(f"Продукт: {t['product']}")
                        with col2:
                            if st.button("Забронировать", key=f"book_{t['id']}"):
                                name = st.session_state.get("student_name", "")
                                if not name:
                                    st.warning("Сначала введите своё имя внизу страницы")
                                else:
                                    if book_topic(t["id"], name):
                                        st.success("Тема забронирована за вами!")
                                        st.rerun()
                                    else:
                                        st.error("Тема уже занята")

        st.divider()
        st.text_input("Ваше ФИО (обязательно для бронирования и сдачи)", key="student_name")
        st.text_input("Класс (например, 8А)", key="student_class")

    with tab2:
        st.subheader("Отправка работы на проверку")
        name = st.session_state.get("student_name", "")
        cls = st.session_state.get("student_class", "")

        if not name:
            st.warning("Введите ФИО на вкладке «Выбрать тему»")
        else:
            all_topics = get_topics()
            my_topics = [t for t in all_topics if t["booked_by"] == name]

            if not my_topics:
                st.info("У вас пока нет забронированных тем.")
            else:
                topic_options = {f"{t['title']} ({t['subject']})": t["id"] for t in my_topics}
                selected = st.selectbox("Выберите тему для сдачи", list(topic_options.keys()))
                topic_id = topic_options[selected]

                uploaded = st.file_uploader(
                    "Загрузите файл работы (pdf, docx, pptx, zip и др.)",
                    type=["pdf", "docx", "doc", "pptx", "ppt", "zip", "rar", "jpg", "png"]
                )

                if st.button("Отправить на проверку", type="primary"):
                    ok, msg = submit_work(topic_id, name, cls, uploaded)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    with tab3:
        st.subheader("Статус моих работ")
        name = st.session_state.get("student_name", "")
        if not name:
            st.warning("Введите ФИО на вкладке «Выбрать тему»")
        else:
            subs = get_student_submissions(name)
            if not subs:
                st.info("Вы ещё не сдавали работы.")
            else:
                for s in subs:
                    status_color = {
                        "на проверке": "🔵",
                        "на доработке": "🟠",
                        "принято": "🟢"
                    }.get(s["status"], "⚪")

                    with st.expander(f"{status_color} {s['title']} — {s['status']}"):
                        st.write(f"**Предмет:** {s['subject']}")
                        st.write(f"**Сдано:** {s['submitted_at']}")
                        st.write(f"**Обновлено:** {s['updated_at']}")
                        if s["teacher_comment"]:
                            st.info(f"Комментарий учителя: {s['teacher_comment']}")
                        if s["drive_link"]:
                            st.markdown(f"[📂 Открыть файл в Google Drive]({s['drive_link']})")
                        if s["status"] == "на доработке":
                            st.warning("Нужно доработать и сдать заново на вкладке «Сдать работу»")

# -------------------- УЧИТЕЛЬ --------------------
else:
    st.title("Панель учителя")

    if "teacher_logged_in" not in st.session_state:
        st.session_state.teacher_logged_in = False

    if not st.session_state.teacher_logged_in:
        pwd = st.text_input("Пароль учителя", type="password")
        if st.button("Войти"):
            if pwd == TEACHER_PASSWORD:
                st.session_state.teacher_logged_in = True
                st.rerun()
            else:
                st.error("Неверный пароль")
        st.stop()

    if st.sidebar.button("Выйти"):
        st.session_state.teacher_logged_in = False
        st.rerun()

    tab_t1, tab_t2, tab_t3, tab_t4 = st.tabs([
        "Работы на проверке",
        "Все темы",
        "Добавить тему",
        "Статистика"
    ])

    with tab_t1:
        st.subheader("Проверка работ")
        filter_status = st.selectbox(
            "Фильтр по статусу",
            ["Все", "на проверке", "на доработке", "принято"]
        )

        if filter_status == "Все":
            subs = get_submissions()
        else:
            subs = get_submissions(status=filter_status)

        if not subs:
            st.info("Нет работ с выбранным статусом.")
        else:
            for s in subs:
                with st.expander(f"{s['student_name']} — {s['title']} ({s['status']})"):
                    st.write(f"**Класс:** {s['student_class']} | **Предмет:** {s['subject']}")
                    st.write(f"**Сдано:** {s['submitted_at']}")

                    if s["drive_link"]:
                        st.markdown(f"[📥 Открыть / скачать работу в Google Drive]({s['drive_link']})")

                    comment = st.text_area(
                        "Комментарий / замечания",
                        value=s["teacher_comment"] or "",
                        key=f"comm_{s['id']}"
                    )

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("✅ Принять", key=f"acc_{s['id']}"):
                            update_submission_status(s["id"], "принято", comment)
                            st.success("Работа принята")
                            st.rerun()
                    with col2:
                        if st.button("🔄 На доработку", key=f"rev_{s['id']}"):
                            update_submission_status(s["id"], "на доработке", comment)
                            st.warning("Отправлено на доработку")
                            st.rerun()
                    with col3:
                        if st.button("🔵 Вернуть на проверку", key=f"pend_{s['id']}"):
                            update_submission_status(s["id"], "на проверке", comment)
                            st.rerun()

    with tab_t2:
        st.subheader("Управление темами")
        st.caption("Просмотр, редактирование, снятие брони и удаление тем.")

        grade_filter = st.selectbox("Фильтр по классу", ["Все", "5", "6", "7", "8", "9", "10", "11"], key="grade_filter_topics")

        if grade_filter == "Все":
            topics = get_topics()
        else:
            topics = get_topics(grade=grade_filter)

        if not topics:
            st.info("Тем пока нет. Добавьте первую тему на вкладке «Добавить тему».")
        else:
            for t in topics:
                status = "🔴 Занята" if t["is_booked"] else "🟢 Свободна"
                with st.expander(f"{status} | {t['grade']} кл. | {t['subject']} — {t['title']}"):
                    st.write(f"**Продукт:** {t['product'] or '—'}")
                    if t["is_booked"]:
                        st.write(f"**Забронировал:** {t['booked_by']} ({t['booked_at']})")
                        if st.button("Снять бронь", key=f"unbook_{t['id']}"):
                            unbook_topic(t["id"])
                            st.rerun()

                    with st.form(key=f"edit_form_{t['id']}"):
                        st.markdown("**Редактировать тему:**")
                        grades = ["5", "6", "7", "8", "9", "10", "11"]
                        idx = grades.index(t["grade"]) if t["grade"] in grades else 3
                        edit_grade = st.selectbox("Класс", grades, index=idx, key=f"eg_{t['id']}")
                        edit_subject = st.text_input("Предмет", value=t["subject"], key=f"es_{t['id']}")
                        edit_title = st.text_input("Тема", value=t["title"], key=f"et_{t['id']}")
                        edit_product = st.text_input("Продукт", value=t["product"] or "", key=f"ep_{t['id']}")

                        col_save, col_del = st.columns(2)
                        with col_save:
                            if st.form_submit_button("💾 Сохранить изменения"):
                                update_topic(t["id"], edit_grade, edit_subject, edit_title, edit_product)
                                st.success("Тема обновлена!")
                                st.rerun()
                        with col_del:
                            if st.form_submit_button("🗑 Удалить тему"):
                                delete_topic(t["id"])
                                st.rerun()

    with tab_t3:
        st.subheader("➕ Добавить новую тему")
        with st.form("add_topic_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                new_grade = st.selectbox("Класс", ["5", "6", "7", "8", "9", "10", "11"])
            with col2:
                new_subject = st.text_input("Предмет / направление", placeholder="Например: Здоровье, Физика, История")

            new_title = st.text_input("Формулировка темы", placeholder="Краткая и понятная тема проекта")
            new_product = st.text_input("Продукт на выходе", placeholder="Например: буклет, презентация, памятка")

            submitted = st.form_submit_button("Добавить тему", type="primary")
            if submitted:
                if new_subject.strip() and new_title.strip():
                    add_topic(new_grade, new_subject.strip(), new_title.strip(), new_product.strip())
                    st.success(f"✅ Тема «{new_title}» добавлена для {new_grade} класса!")
                    st.rerun()
                else:
                    st.error("Заполните хотя бы предмет и формулировку темы")

    with tab_t4:
        st.subheader("Статистика")
        all_topics = get_topics()
        free = len([t for t in all_topics if t["is_booked"] == 0])
        booked = len([t for t in all_topics if t["is_booked"] == 1])
        all_subs = get_submissions()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Всего тем", len(all_topics))
        col2.metric("Свободных", free)
        col3.metric("Забронировано", booked)
        col4.metric("Сданных работ", len(all_subs))

        st.write("---")
        st.write("**По статусам работ:**")
        statuses = {}
        for s in all_subs:
            statuses[s["status"]] = statuses.get(s["status"], 0) + 1
        for k, v in statuses.items():
            st.write(f"- {k}: {v}")

st.sidebar.markdown("---")
st.sidebar.caption("Данные хранятся в Google Таблицах и Диске")
