import streamlit as st
import sqlite3
import os
import hashlib
from datetime import datetime
from pathlib import Path
import shutil

# ==================== НАСТРОЙКИ ====================
DB_PATH = "data/projects.db"
UPLOAD_DIR = Path("uploads")
TEACHER_PASSWORD = "teacher2026"  # Смените пароль!

UPLOAD_DIR.mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

# ==================== БАЗА ДАННЫХ ====================
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Темы
    c.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grade TEXT NOT NULL,
            subject TEXT NOT NULL,
            title TEXT NOT NULL,
            product TEXT,
            is_booked INTEGER DEFAULT 0,
            booked_by TEXT,
            booked_at TEXT
        )
    """)
    
    # Работы учеников
    c.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER,
            student_name TEXT NOT NULL,
            student_class TEXT,
            filename TEXT,
            filepath TEXT,
            status TEXT DEFAULT 'на проверке',
            teacher_comment TEXT,
            submitted_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (topic_id) REFERENCES topics (id)
        )
    """)
    
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ==================== ФУНКЦИИ ДЛЯ ТЕМ ====================
def add_topic(grade, subject, title, product):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO topics (grade, subject, title, product) VALUES (?, ?, ?, ?)",
        (grade, subject, title, product)
    )
    conn.commit()
    conn.close()

def get_topics(grade=None, only_free=False):
    conn = get_connection()
    c = conn.cursor()
    query = "SELECT * FROM topics"
    params = []
    conditions = []
    
    if grade:
        conditions.append("grade = ?")
        params.append(grade)
    if only_free:
        conditions.append("is_booked = 0")
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY subject, title"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def book_topic(topic_id, student_name):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT is_booked FROM topics WHERE id = ?", (topic_id,))
    row = c.fetchone()
    if row and row["is_booked"] == 1:
        conn.close()
        return False
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute(
        "UPDATE topics SET is_booked = 1, booked_by = ?, booked_at = ? WHERE id = ?",
        (student_name, now, topic_id)
    )
    conn.commit()
    conn.close()
    return True

def unbook_topic(topic_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE topics SET is_booked = 0, booked_by = NULL, booked_at = NULL WHERE id = ?",
        (topic_id,)
    )
    conn.commit()
    conn.close()

def delete_topic(topic_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    conn.commit()
    conn.close()

def update_topic(topic_id, grade, subject, title, product):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE topics 
        SET grade = ?, subject = ?, title = ?, product = ?
        WHERE id = ?
    """, (grade, subject, title, product, topic_id))
    conn.commit()
    conn.close()

# ==================== ФУНКЦИИ ДЛЯ РАБОТ ====================
def submit_work(topic_id, student_name, student_class, uploaded_file):
    if uploaded_file is None:
        return False, "Файл не выбран"
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in student_name if c.isalnum() or c in " _-").strip()
    ext = Path(uploaded_file.name).suffix
    filename = f"{timestamp}_{safe_name}_{topic_id}{ext}"
    filepath = UPLOAD_DIR / filename
    
    with open(filepath, "wb") as f:
        f.write(uploaded_file.getbuffer())
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO submissions 
        (topic_id, student_name, student_class, filename, filepath, status, submitted_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'на проверке', ?, ?)
    """, (topic_id, student_name, student_class, filename, str(filepath), now, now))
    conn.commit()
    conn.close()
    return True, "Работа успешно отправлена!"

def get_submissions(status=None):
    conn = get_connection()
    c = conn.cursor()
    if status:
        c.execute("""
            SELECT s.*, t.title, t.subject, t.grade 
            FROM submissions s 
            LEFT JOIN topics t ON s.topic_id = t.id
            WHERE s.status = ?
            ORDER BY s.submitted_at DESC
        """, (status,))
    else:
        c.execute("""
            SELECT s.*, t.title, t.subject, t.grade 
            FROM submissions s 
            LEFT JOIN topics t ON s.topic_id = t.id
            ORDER BY s.submitted_at DESC
        """)
    rows = c.fetchall()
    conn.close()
    return rows

def update_submission_status(sub_id, status, comment=""):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute("""
        UPDATE submissions 
        SET status = ?, teacher_comment = ?, updated_at = ?
        WHERE id = ?
    """, (status, comment, now, sub_id))
    conn.commit()
    conn.close()

def get_student_submissions(student_name):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT s.*, t.title, t.subject 
        FROM submissions s 
        LEFT JOIN topics t ON s.topic_id = t.id
        WHERE s.student_name = ?
        ORDER BY s.submitted_at DESC
    """, (student_name,))
    rows = c.fetchall()
    conn.close()
    return rows

# ==================== ЗАПОЛНЕНИЕ ПРИМЕРНЫМИ ТЕМАМИ ====================
# Автоматическое добавление тем отключено — учитель добавляет темы сам через панель.
def seed_topics():
    pass

# ==================== ИНТЕРФЕЙС ====================
st.set_page_config(
    page_title="Темы проектов — бронирование",
    page_icon="📚",
    layout="wide"
)

init_db()
seed_topics()

# Боковая панель — выбор роли
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
                if subj not in subjects:
                    subjects[subj] = []
                subjects[subj].append(t)
            
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
                                        st.success(f"Тема забронирована за вами!")
                                        st.rerun()
                                    else:
                                        st.error("Тема уже занята")
        
        st.divider()
        student_name = st.text_input("Ваше ФИО (обязательно для бронирования и сдачи)", key="student_name")
        student_class = st.text_input("Класс (например, 8А)", key="student_class")
    
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
                    
                    if s["filepath"] and os.path.exists(s["filepath"]):
                        with open(s["filepath"], "rb") as f:
                            st.download_button(
                                "📥 Скачать работу",
                                f,
                                file_name=s["filename"],
                                key=f"dl_{s['id']}"
                            )
                    
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
        st.caption("Здесь вы можете просматривать, редактировать, снимать бронь и удалять темы.")
        
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
                        edit_grade = st.selectbox("Класс", ["5", "6", "7", "8", "9", "10", "11"], 
                                                   index=["5","6","7","8","9","10","11"].index(t["grade"]) if t["grade"] in ["5","6","7","8","9","10","11"] else 3,
                                                   key=f"eg_{t['id']}")
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
        st.markdown("Заполните форму ниже, чтобы добавить тему для учеников.")
        
        with st.form("add_topic_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                new_grade = st.selectbox("Класс", ["5", "6", "7", "8", "9", "10", "11"])
            with col2:
                new_subject = st.text_input("Предмет / направление", placeholder="Например: Здоровье, Английский язык, Туризм")
            
            new_title = st.text_input("Формулировка темы", placeholder="Краткая и понятная тема проекта")
            new_product = st.text_input("Продукт на выходе", placeholder="Например: буклет, презентация, памятка, карта")
            
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
st.sidebar.caption("Пароль учителя по умолчанию: teacher2026")
st.sidebar.caption("Смените его в коде (переменная TEACHER_PASSWORD)")
