import streamlit as st
from logic import (
    init_sheets, get_topics, get_topics_cached, get_student_booking, book_topic, unbook_topic,
    delete_topic, update_topic, add_topic, add_topics_bulk,
    get_materials, add_material, delete_material,
    submit_work, get_submissions, update_submission_status, get_student_submissions,
    get_action_log, topics_to_csv, submissions_to_csv, TEACHER_PASSWORD, log_action,
)
from datetime import datetime
import csv
import io

CLASSES = ["8А", "8Б", "8В", "8Г", "8Д", "8Е"]

st.set_page_config(page_title="Темы проектов", page_icon="📚", layout="wide")

if "gcp_service_account" not in st.secrets or "SPREADSHEET_ID" not in st.secrets or "DRIVE_FOLDER_ID" not in st.secrets:
    st.error("Не настроены Google Secrets. См. README.")
    st.stop()

try:
    init_sheets()
except Exception as e:
    err = str(e)
    if "429" in err or "Quota" in err:
        st.warning(
            "⏳ Google временно ограничил число запросов (лимит API). "
            "Подождите **1–2 минуты** и обновите страницу **один раз**."
        )
        st.stop()
    raise

st.sidebar.title("📚 Темы проектов")
role = st.sidebar.radio("Кто вы?", ["Ученик", "Учитель"])

if role == "Ученик":
    st.title("Бронирование темы проекта")

    with st.expander("ℹ️ Как пользоваться", expanded=False):
        st.markdown("""
**Как выбрать тему:** рекомендация учителя, интересы, икигай.

1. Введите ФИО и класс (8А–8Е).
2. Выберите свободную тему (общий список для всех 8 классов).
3. Забронируйте (одна тема на ученика).
4. Сдайте работу на вкладке «Сдать работу».
5. Статус — во вкладке «Мой кабинет».
        """)

    materials = get_materials()
    if materials:
        st.subheader("📎 Материалы от учителя")
        for m in materials:
            with st.expander(f"📄 {m['title']}" + (f" — {m['description']}" if m["description"] else "")):
                st.caption(f"Загружено: {m['uploaded_at']} | Файл: {m['filename']}")
                if m["drive_link"]:
                    st.markdown(f"[⬇️ Скачать / открыть]({m['drive_link']})")

    tab1, tab2, tab3 = st.tabs(["1. Выбрать тему", "2. Сдать работу", "3. Мой кабинет"])

    with tab1:
        st.subheader("Свободные темы")
        col_a, col_b = st.columns(2)
        with col_a:
            student_name = st.text_input("Ваше ФИО (обязательно)", key="student_name")
        with col_b:
            student_class = st.selectbox("Класс", CLASSES, key="student_class")

        if student_name:
            booking = get_student_booking(student_name)
            if booking:
                st.success(f"✅ Ваша тема: **{booking['title']}** ({booking['subject']})"
                           + (f" | Дедлайн: {booking['deadline']}" if booking["deadline"] else ""))
            else:
                st.info("У вас пока нет забронированной темы — выберите ниже.")

        st.caption("Темы общие для 8А–8Е. Класс сохраняется при брони и сдаче.")
        col_s, col_r = st.columns([4, 1])
        with col_s:
            search_q = st.text_input("Поиск по темам", placeholder="слово из темы или предмета")
        with col_r:
            st.write("")
            st.write("")
            if st.button("🔄 Обновить", key="refresh_topics"):
                get_topics_cached.clear()
                st.rerun()

        all_for_count = get_topics_cached()
        free_count = sum(1 for t in all_for_count if t["is_booked"] != 1)
        st.caption(f"В базе тем: **{len(all_for_count)}** · свободно: **{free_count}** · занято: **{len(all_for_count) - free_count}**")

        topics = get_topics(only_free=True, search=search_q or None)

        if not topics:
            if len(all_for_count) == 0:
                st.warning(
                    "В таблице пока нет тем (или они не читаются). "
                    "Учитель добавляет темы во вкладке «Добавить темы». "
                    "Проверьте лист **topics**: заголовки "
                    "`id | grade | subject | title | product | is_booked | booked_by | booked_at | deadline`."
                )
            else:
                st.info("Свободных тем нет — все забронированы.")
                for t in get_topics(only_free=False, search=search_q or None):
                    if t["is_booked"] == 1:
                        st.markdown(f"🔒 **{t['title']}** ({t['subject']}) — {t['booked_by'] or 'занята'}")
        else:
            subjects = {}
            for t in topics:
                subjects.setdefault(t["subject"] or "Без предмета", []).append(t)
            for subj, items in subjects.items():
                with st.expander(f"📌 {subj} ({len(items)})", expanded=True):
                    for t in items:
                        c1, c2 = st.columns([4, 1])
                        with c1:
                            st.markdown(f"**{t['title']}**")
                            extra = []
                            if t["product"]:
                                extra.append(f"Продукт: {t['product']}")
                            if t["deadline"]:
                                extra.append(f"Дедлайн: {t['deadline']}")
                            if extra:
                                st.caption(" | ".join(extra))
                        with c2:
                            if st.button("Забронировать", key=f"book_{t['id']}"):
                                if not student_name:
                                    st.warning("Сначала введите ФИО")
                                else:
                                    ok, msg = book_topic(t["id"], student_name)
                                    if ok:
                                        st.success(msg)
                                        st.rerun()
                                    else:
                                        st.error(msg)

    with tab2:
        st.subheader("Отправка работы")
        name = st.session_state.get("student_name", "")
        cls = st.session_state.get("student_class", "")
        if not name:
            st.warning("Введите ФИО на вкладке «Выбрать тему».")
        else:
            booking = get_student_booking(name)
            if not booking:
                st.info("Сначала забронируйте тему.")
            else:
                st.write(f"Тема: **{booking['title']}**")
                if booking["deadline"]:
                    st.caption(f"Дедлайн: {booking['deadline']}")
                uploaded = st.file_uploader(
                    "Файл работы",
                    type=["pdf", "docx", "doc", "pptx", "ppt", "zip", "rar", "jpg", "png"],
                )
                if st.button("Отправить на проверку", type="primary"):
                    ok, msg = submit_work(booking["id"], name, cls, uploaded)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    with tab3:
        st.subheader("Мой кабинет")
        name = st.session_state.get("student_name", "")
        if not name:
            st.warning("Введите ФИО на вкладке «Выбрать тему».")
        else:
            booking = get_student_booking(name)
            st.markdown("#### Забронированная тема")
            if booking:
                st.write(f"**{booking['title']}**")
                st.caption(f"Предмет: {booking['subject']}"
                           + (f" | Дедлайн: {booking['deadline']}" if booking['deadline'] else ""))
            else:
                st.info("Тема ещё не выбрана.")
            st.markdown("#### Мои работы")
            subs = get_student_submissions(name)
            if not subs:
                st.info("Работы ещё не сдавались.")
            else:
                for s in subs:
                    color = {"на проверке": "🔵", "на доработке": "🟠", "принято": "🟢"}.get(s["status"], "⚪")
                    with st.expander(f"{color} {s['title']} — {s['status']}"):
                        st.write(f"Сдано: {s['submitted_at']}")
                        if s["teacher_comment"]:
                            st.info(f"Комментарий: {s['teacher_comment']}")
                        if s["drive_link"]:
                            st.markdown(f"[📂 Файл]({s['drive_link']})")

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

    tab_t1, tab_t2, tab_t3, tab_t4, tab_t5, tab_t6 = st.tabs([
        "Работы", "Темы", "Добавить темы", "Материалы", "Экспорт", "Лог",
    ])

    with tab_t1:
        st.subheader("Проверка работ")
        c1, c2 = st.columns(2)
        with c1:
            filter_status = st.selectbox("Статус", ["Все", "на проверке", "на доработке", "принято"])
        with c2:
            sub_search = st.text_input("Поиск", key="sub_search")
        if filter_status == "Все":
            subs = get_submissions(search=sub_search or None)
        else:
            subs = get_submissions(status=filter_status, search=sub_search or None)
        if not subs:
            st.info("Нет работ.")
        else:
            for s in subs:
                with st.expander(f"{s['student_name']} ({s['student_class']}) — {s['title']} [{s['status']}]"):
                    if s["drive_link"]:
                        st.markdown(f"[📥 Открыть]({s['drive_link']})")
                    comment = st.text_area("Комментарий", value=s["teacher_comment"] or "", key=f"comm_{s['id']}")
                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button("✅ Принять", key=f"acc_{s['id']}"):
                            update_submission_status(s["id"], "принято", comment)
                            st.rerun()
                    with b2:
                        if st.button("🔄 На доработку", key=f"rev_{s['id']}"):
                            update_submission_status(s["id"], "на доработке", comment)
                            st.rerun()
                    with b3:
                        if st.button("🔵 На проверку", key=f"pend_{s['id']}"):
                            update_submission_status(s["id"], "на проверке", comment)
                            st.rerun()

    with tab_t2:
        st.subheader("Забронировать тему за ученика")
        free_topics = get_topics(only_free=True)
        if not free_topics:
            st.info("Нет свободных тем.")
        else:
            with st.form("teacher_book_form"):
                tb_name = st.text_input("ФИО ученика")
                tb_class = st.selectbox("Класс", CLASSES, key="tb_class")
                options = {f"{t['subject']} — {t['title']}": t["id"] for t in free_topics}
                tb_label = st.selectbox("Тема", list(options.keys()))
                tb_note = st.text_input("Комментарий (необязательно)")
                if st.form_submit_button("Забронировать", type="primary"):
                    if not tb_name.strip():
                        st.error("Укажите ФИО")
                    else:
                        ok, msg = book_topic(options[tb_label], tb_name.strip())
                        if ok:
                            if tb_note.strip():
                                log_action("учитель", "рекомендация + бронь",
                                           f"{tb_name.strip()} ({tb_class}): {tb_note.strip()}")
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        st.divider()
        st.subheader("Управление темами")
        if st.button("🔄 Обновить список тем"):
            get_topics_cached.clear()
            st.rerun()
        c1, c2 = st.columns(2)
        with c1:
            grade_filter = st.selectbox("Класс", ["Все"] + CLASSES, key="gf")
        with c2:
            topic_search = st.text_input("Поиск", key="topic_search")
        if grade_filter == "Все":
            topics = get_topics(search=topic_search or None)
        else:
            topics = get_topics(grade=grade_filter, search=topic_search or None)
        st.caption(f"Показано тем: {len(topics)} (всего в базе: {len(get_topics_cached())})")
        if not topics:
            st.info("Тем нет. Добавьте на вкладке «Добавить темы».")
        else:
            for t in topics:
                status = "🔴 Занята" if t["is_booked"] else "🟢 Свободна"
                with st.expander(f"{status} | {t['grade']} | {t['subject']} — {t['title']}"):
                    st.write(f"Продукт: {t['product'] or '—'}")
                    if t["is_booked"]:
                        st.write(f"Забронировал: {t['booked_by']}")
                        if st.button("Снять бронь", key=f"unbook_{t['id']}"):
                            unbook_topic(t["id"])
                            st.rerun()
                    with st.form(key=f"edit_{t['id']}"):
                        idx = CLASSES.index(t["grade"]) if t["grade"] in CLASSES else 0
                        eg = st.selectbox("Класс", CLASSES, index=idx, key=f"eg_{t['id']}")
                        es = st.text_input("Предмет", value=t["subject"], key=f"es_{t['id']}")
                        et = st.text_input("Тема", value=t["title"], key=f"et_{t['id']}")
                        ep = st.text_input("Продукт", value=t["product"] or "", key=f"ep_{t['id']}")
                        ed = st.text_input("Дедлайн", value=t["deadline"] or "", key=f"ed_{t['id']}")
                        cs, cd = st.columns(2)
                        with cs:
                            if st.form_submit_button("💾 Сохранить"):
                                update_topic(t["id"], eg, es, et, ep, ed)
                                st.rerun()
                        with cd:
                            if st.form_submit_button("🗑 Удалить"):
                                delete_topic(t["id"])
                                st.rerun()

    with tab_t3:
        st.subheader("Добавить одну тему")
        with st.form("add_one", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                ng = st.selectbox("Класс", CLASSES)
            with c2:
                ns = st.text_input("Предмет")
            nt = st.text_input("Тема")
            np_ = st.text_input("Продукт")
            nd = st.text_input("Дедлайн", placeholder="15.05.2026")
            if st.form_submit_button("Добавить", type="primary"):
                if ns.strip() and nt.strip():
                    add_topic(ng, ns.strip(), nt.strip(), np_.strip(), nd.strip())
                    st.success("Тема добавлена")
                    st.rerun()
                else:
                    st.error("Заполните предмет и тему")

        st.divider()
        st.subheader("Массовое добавление")
        st.caption("Формат: Класс;Предмет;Тема;Продукт;Дедлайн")
        st.code("8А;Физика;Какие материалы лучше сохраняют тепло;сравнение;20.05.2026", language=None)
        bulk_text = st.text_area("Вставьте строки", height=150)
        uploaded_csv = st.file_uploader("Или CSV", type=["csv"])
        if st.button("Загрузить пакет тем"):
            rows = []
            if bulk_text.strip():
                for line in bulk_text.strip().splitlines():
                    parts = [p.strip() for p in line.split(";")]
                    if len(parts) >= 3:
                        rows.append({
                            "grade": parts[0], "subject": parts[1], "title": parts[2],
                            "product": parts[3] if len(parts) > 3 else "",
                            "deadline": parts[4] if len(parts) > 4 else "",
                        })
            if uploaded_csv is not None:
                text = uploaded_csv.getvalue().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(text))
                for r in reader:
                    rows.append({
                        "grade": r.get("grade") or r.get("Класс") or "8А",
                        "subject": r.get("subject") or r.get("Предмет") or "",
                        "title": r.get("title") or r.get("Тема") or "",
                        "product": r.get("product") or r.get("Продукт") or "",
                        "deadline": r.get("deadline") or r.get("Дедлайн") or "",
                    })
            if rows:
                n = add_topics_bulk(rows)
                st.success(f"Добавлено тем: {n}")
                st.rerun()
            else:
                st.warning("Нет данных")

    with tab_t4:
        st.subheader("Материалы")
        with st.form("add_mat", clear_on_submit=True):
            mt = st.text_input("Название")
            md = st.text_input("Описание")
            mf = st.file_uploader("Файл", type=["pdf", "docx", "pptx", "zip", "jpg", "png", "xlsx"])
            if st.form_submit_button("Опубликовать"):
                if mt.strip() and mf is not None:
                    add_material(mt.strip(), md.strip(), mf)
                    st.success("Опубликовано")
                    st.rerun()
                else:
                    st.error("Название и файл обязательны")
        for m in get_materials():
            with st.expander(f"📄 {m['title']}"):
                if m["drive_link"]:
                    st.markdown(f"[Открыть]({m['drive_link']})")
                if st.button("Удалить", key=f"delmat_{m['id']}"):
                    delete_material(m["id"])
                    st.rerun()

    with tab_t5:
        st.subheader("Экспорт")
        all_topics = get_topics()
        all_subs = get_submissions()
        st.download_button("📥 Темы CSV", data=topics_to_csv(all_topics),
                           file_name=f"topics_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")
        st.download_button("📥 Работы CSV", data=submissions_to_csv(all_subs),
                           file_name=f"submissions_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")
        st.metric("Тем", len(all_topics))
        st.metric("Работ", len(all_subs))

    with tab_t6:
        st.subheader("Лог")
        for L in get_action_log(150):
            st.text(f"{L['timestamp']} | {L['actor']} | {L['action']} | {L['details']}")

st.sidebar.markdown("---")
st.sidebar.caption("Данные: Google Таблицы и Диск")
