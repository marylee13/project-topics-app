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

PRODUCT_TIPS = {
    "презентация": "8–12 слайдов, крупный шрифт, один тезис на слайд, вывод и источники.",
    "буклет": "2–3 складки, заголовок, 3–5 блоков фактов, вывод «что делать».",
    "памятка": "1 страница: заголовок, 5–7 правил, чего избегать.",
    "инфографика": "Один лист: заголовок, 3–5 цифр/блоков, источник данных.",
    "гайд": "Цель → шаги 1–2–3 → ошибки → чек-лист.",
    "инструкция": "Шаги по порядку, предупреждения безопасности.",
    "карта": "Легенда, подписи, 3–5 пояснений, вывод.",
    "опрос": "5–10 вопросов, сколько ответило, графики, вывод.",
    "эксперимент": "Цель, ход, результат, вывод.",
    "видео": "30–90 сек, план, титры с выводом.",
    "аудио": "3–7 мин, план, вывод в конце.",
    "комикс": "6–8 кадров, одна идея, читаемый текст.",
    "сравнение": "Таблица А/Б, критерии, итог.",
    "чеклист": "Пункты да/нет и кратко почему важно.",
    "дневник": "Даты, 5–7 записей, итог.",
    "рекомендации": "Кому, 5–7 советов, предостережения.",
}

def product_tip(product: str) -> str:
    if not product:
        return ""
    p = product.lower()
    for key, tip in PRODUCT_TIPS.items():
        if key in p:
            return tip
    return "Укажите цель, для кого продукт, 3–5 фактов и понятный вывод."

st.set_page_config(page_title="Темы проектов", page_icon="📚", layout="wide")

if "gcp_service_account" not in st.secrets or "SPREADSHEET_ID" not in st.secrets or "DRIVE_FOLDER_ID" not in st.secrets:
    st.error("Не настроены Google Secrets. См. README.")
    st.stop()

try:
    init_sheets()
except Exception as e:
    err = str(e)
    if "429" in err or "Quota" in err:
        st.warning("⏳ Лимит Google API. Подождите 1–2 минуты и обновите страницу один раз.")
        st.stop()
    raise

st.sidebar.title("📚 Темы проектов")
role = st.sidebar.radio("Кто вы?", ["Ученик", "Учитель"])

if role == "Ученик":
    st.title("Бронирование темы проекта")

    col_a, col_b = st.columns(2)
    with col_a:
        student_name = st.text_input("Ваше ФИО (обязательно)", key="student_name")
    with col_b:
        student_class = st.selectbox("Класс", CLASSES, key="student_class")

    booking = get_student_booking(student_name) if student_name else None
    if student_name and booking:
        st.success(
            f"### ✅ Моя тема\n**{booking['title']}**\n\n"
            f"Предмет: {booking['subject']}"
            + (f" · Продукт: {booking['product']}" if booking.get("product") else "")
            + (f" · Дедлайн: **{booking['deadline']}**" if booking.get("deadline") else "")
        )
        if booking.get("product"):
            tip = product_tip(booking["product"])
            if tip:
                st.info(f"**Как оформить «{booking['product']}»:** {tip}")
    elif student_name:
        st.info("Тема ещё не выбрана — вкладка «Выбрать тему».")
    else:
        st.caption("Введите ФИО — здесь появится ваша тема на всех вкладках.")

    with st.expander("ℹ️ Как пользоваться", expanded=False):
        st.markdown("""
1. ФИО и класс → забронируйте одну тему (🟢 свободно, 🔴 занята).
2. Сдайте файл (можно пересдать — старая версия сохранится).
3. В кабинете смотрите статус и историю.
        """)

    materials = get_materials()
    if materials:
        st.subheader("📎 Материалы от учителя")
        for m in materials:
            with st.expander(f"📄 {m['title']}"):
                if m["drive_link"]:
                    st.markdown(f"[⬇️ Открыть]({m['drive_link']})")

    tab1, tab2, tab3 = st.tabs(["1. Выбрать тему", "2. Сдать работу", "3. Мой кабинет"])

    with tab1:
        st.subheader("Список тем")
        st.caption("🟢 свободно · 🔴 занята · темы общие для 8А–8Е")
        col_s, col_r = st.columns([4, 1])
        with col_s:
            search_q = st.text_input("Поиск", placeholder="тема или предмет")
        with col_r:
            st.write(""); st.write("")
            if st.button("🔄 Обновить", key="refresh_topics"):
                get_topics_cached.clear()
                st.rerun()

        all_for_count = get_topics_cached()
        free_count = sum(1 for t in all_for_count if t["is_booked"] != 1)
        st.caption(f"В базе: **{len(all_for_count)}** · 🟢 свободно: **{free_count}** · 🔴 занято: **{len(all_for_count) - free_count}**")

        topics = get_topics(only_free=False, search=search_q or None)

        if not topics:
            if not all_for_count:
                st.warning("Тем пока нет. Учитель добавит их на вкладке «Добавить темы».")
            else:
                st.info("По запросу ничего не найдено.")
        else:
            subjects = {}
            for t in topics:
                subjects.setdefault(t["subject"] or "Без предмета", []).append(t)
            for subj, items in subjects.items():
                free_in = sum(1 for t in items if t["is_booked"] != 1)
                with st.expander(f"📌 {subj} (🟢 {free_in} / {len(items)})", expanded=True):
                    for t in items:
                        is_busy = t["is_booked"] == 1
                        mark = "🔴" if is_busy else "🟢"
                        c1, c2 = st.columns([4, 1])
                        with c1:
                            st.markdown(f"{mark} **{t['title']}**")
                            extra = []
                            if is_busy:
                                extra.append(f"Занята: {t['booked_by'] or '—'}")
                            else:
                                extra.append("Свободна")
                            if t.get("product"):
                                extra.append(f"Продукт: {t['product']}")
                            if t.get("deadline"):
                                extra.append(f"Дедлайн: {t['deadline']}")
                            st.caption(" | ".join(extra))
                            if not is_busy and t.get("product"):
                                tip = product_tip(t["product"])
                                if tip:
                                    st.caption(f"💡 {tip}")
                        with c2:
                            if is_busy:
                                st.caption("занята")
                            else:
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
            st.warning("Введите ФИО вверху страницы.")
        else:
            booking = get_student_booking(name)
            if not booking:
                st.info("Сначала забронируйте тему.")
            else:
                st.write(f"Тема: **{booking['title']}**")
                if booking.get("product"):
                    tip = product_tip(booking["product"])
                    if tip:
                        st.info(f"💡 {tip}")
                existing = [s for s in get_student_submissions(name) if s["topic_id"] == booking["id"]]
                if existing:
                    st.warning("Можно **пересдать** — предыдущий файл сохранится в истории.")
                    cur = existing[0]
                    st.caption(f"Статус: **{cur['status']}** · {cur['filename']}")
                    if cur.get("drive_link"):
                        st.markdown(f"[Текущий файл]({cur['drive_link']})")
                uploaded = st.file_uploader("Файл", type=["pdf", "docx", "doc", "pptx", "ppt", "zip", "rar", "jpg", "png"])
                label = "Пересдать работу" if existing else "Отправить на проверку"
                if st.button(label, type="primary"):
                    ok, msg = submit_work(booking["id"], name, cls, uploaded)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    with tab3:
        st.subheader("Мой кабинет")
        name = st.session_state.get("student_name", "")
        if not name:
            st.warning("Введите ФИО вверху страницы.")
        else:
            booking = get_student_booking(name)
            if booking:
                st.markdown(f"#### {booking['title']}")
                st.caption(booking["subject"] + (f" · {booking['product']}" if booking.get("product") else ""))
                if booking.get("product"):
                    tip = product_tip(booking["product"])
                    if tip:
                        st.info(f"💡 {tip}")
            else:
                st.info("Тема не выбрана.")
            st.markdown("#### Работы и история статусов")
            subs = get_student_submissions(name)
            if not subs:
                st.info("Работы ещё не сдавались.")
            else:
                for s in subs:
                    color = {"на проверке": "🔵", "на доработке": "🟠", "принято": "🟢"}.get(s["status"], "⚪")
                    with st.expander(f"{color} {s['title']} — {s['status']}", expanded=True):
                        st.write(f"Сдано: {s['submitted_at']} · Обновлено: {s['updated_at']}")
                        if s["teacher_comment"]:
                            st.info(f"Комментарий: {s['teacher_comment']}")
                        if s["drive_link"]:
                            st.markdown(f"[📂 Текущий файл]({s['drive_link']})")
                        st.markdown("**История статусов**")
                        hist = (s.get("status_history") or "").strip()
                        if hist:
                            for line in hist.splitlines():
                                if line.strip():
                                    st.markdown(f"- {line.strip()}")
                        else:
                            st.caption(f"• {s['submitted_at'] or '—'} — сдано · сейчас: {s['status']}")
                        versions = (s.get("versions") or "").strip()
                        if versions:
                            st.markdown("**Предыдущие версии**")
                            for part in versions.split(";;"):
                                part = part.strip()
                                if not part:
                                    continue
                                bits = [b.strip() for b in part.split("|")]
                                if len(bits) >= 3 and bits[2].startswith("http"):
                                    st.markdown(f"- {bits[0]} · {bits[1]} · [файл]({bits[2]})")
                                else:
                                    st.caption(f"- {part}")
                        if s["status"] == "на доработке":
                            st.warning("Нужна доработка — вкладка «Сдать работу».")

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
        subs = get_submissions(search=sub_search or None) if filter_status == "Все" else get_submissions(status=filter_status, search=sub_search or None)
        if not subs:
            st.info("Нет работ.")
        else:
            for s in subs:
                with st.expander(f"{s['student_name']} ({s['student_class']}) — {s['title']} [{s['status']}]"):
                    if s["drive_link"]:
                        st.markdown(f"[📥 Открыть]({s['drive_link']})")
                    if s.get("status_history"):
                        st.caption("История: " + " → ".join([x.strip() for x in s["status_history"].splitlines() if x.strip()][-3:]))
                    comment = st.text_area("Комментарий", value=s["teacher_comment"] or "", key=f"comm_{s['id']}")
                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button("✅ Принять", key=f"acc_{s['id']}"):
                            update_submission_status(s["id"], "принято", comment); st.rerun()
                    with b2:
                        if st.button("🔄 На доработку", key=f"rev_{s['id']}"):
                            update_submission_status(s["id"], "на доработке", comment); st.rerun()
                    with b3:
                        if st.button("🔵 На проверку", key=f"pend_{s['id']}"):
                            update_submission_status(s["id"], "на проверке", comment); st.rerun()

    with tab_t2:
        st.subheader("Забронировать за ученика")
        free_topics = get_topics(only_free=True)
        if free_topics:
            with st.form("teacher_book_form"):
                tb_name = st.text_input("ФИО")
                tb_class = st.selectbox("Класс", CLASSES, key="tb_class")
                options = {f"{t['subject']} — {t['title']}": t["id"] for t in free_topics}
                tb_label = st.selectbox("Тема", list(options.keys()))
                tb_note = st.text_input("Комментарий")
                if st.form_submit_button("Забронировать", type="primary"):
                    if tb_name.strip():
                        ok, msg = book_topic(options[tb_label], tb_name.strip())
                        if ok:
                            if tb_note.strip():
                                log_action("учитель", "рекомендация + бронь", f"{tb_name.strip()} ({tb_class}): {tb_note.strip()}")
                            st.success(msg); st.rerun()
                        else:
                            st.error(msg)
        st.divider()
        st.subheader("Управление темами")
        if st.button("🔄 Обновить список"):
            get_topics_cached.clear(); st.rerun()
        grade_filter = st.selectbox("Класс", ["Все"] + CLASSES, key="gf")
        topic_search = st.text_input("Поиск", key="topic_search")
        topics = get_topics(search=topic_search or None) if grade_filter == "Все" else get_topics(grade=grade_filter, search=topic_search or None)
        st.caption(f"Показано: {len(topics)}")
        for t in topics:
            status = "🔴" if t["is_booked"] else "🟢"
            with st.expander(f"{status} {t['subject']} — {t['title']}"):
                if t["is_booked"] and st.button("Снять бронь", key=f"unbook_{t['id']}"):
                    unbook_topic(t["id"]); st.rerun()
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
                            update_topic(t["id"], eg, es, et, ep, ed); st.rerun()
                    with cd:
                        if st.form_submit_button("🗑 Удалить"):
                            delete_topic(t["id"]); st.rerun()

    with tab_t3:
        st.subheader("Добавить тему")
        with st.form("add_one", clear_on_submit=True):
            ng = st.selectbox("Класс", CLASSES)
            ns = st.text_input("Предмет")
            nt = st.text_input("Тема")
            np_ = st.text_input("Продукт")
            nd = st.text_input("Дедлайн")
            if st.form_submit_button("Добавить", type="primary"):
                if ns.strip() and nt.strip():
                    add_topic(ng, ns.strip(), nt.strip(), np_.strip(), nd.strip())
                    st.success("Добавлено"); st.rerun()
        st.subheader("Массовое добавление")
        st.code("8А;Физика;Тема;продукт;20.05.2026")
        bulk_text = st.text_area("Строки", height=120)
        if st.button("Загрузить пакет"):
            rows = []
            for line in bulk_text.strip().splitlines():
                parts = [p.strip() for p in line.split(";")]
                if len(parts) >= 3:
                    rows.append({"grade": parts[0], "subject": parts[1], "title": parts[2],
                                 "product": parts[3] if len(parts) > 3 else "",
                                 "deadline": parts[4] if len(parts) > 4 else ""})
            if rows:
                st.success(f"Добавлено: {add_topics_bulk(rows)}"); st.rerun()

    with tab_t4:
        st.subheader("Материалы")
        with st.form("add_mat", clear_on_submit=True):
            mt = st.text_input("Название")
            md = st.text_input("Описание")
            mf = st.file_uploader("Файл")
            if st.form_submit_button("Опубликовать"):
                if mt.strip() and mf is not None:
                    add_material(mt.strip(), md.strip(), mf); st.success("Ок"); st.rerun()
        for m in get_materials():
            with st.expander(m["title"]):
                if m["drive_link"]:
                    st.markdown(f"[Открыть]({m['drive_link']})")
                if st.button("Удалить", key=f"delmat_{m['id']}"):
                    delete_material(m["id"]); st.rerun()

    with tab_t5:
        all_topics = get_topics(); all_subs = get_submissions()
        st.download_button("Темы CSV", data=topics_to_csv(all_topics), file_name="topics.csv", mime="text/csv")
        st.download_button("Работы CSV", data=submissions_to_csv(all_subs), file_name="subs.csv", mime="text/csv")
        st.metric("Тем", len(all_topics)); st.metric("Работ", len(all_subs))

    with tab_t6:
        for L in get_action_log(150):
            st.text(f"{L['timestamp']} | {L['actor']} | {L['action']} | {L['details']}")

st.sidebar.markdown("---")
st.sidebar.caption("Google Таблицы и Диск")
