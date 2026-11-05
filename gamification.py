from datetime import datetime
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

import logic


def _font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _class_records():
    ws = logic.ensure_worksheet("class_settings")
    return ws, logic.rows_to_records(logic.safe_get_all_values(ws))


def set_class_size(class_name, student_count):
    class_name = (class_name or "").strip()
    try:
        student_count = int(student_count)
    except (TypeError, ValueError):
        return False, "Укажите количество учеников"
    if not class_name or student_count < 1:
        return False, "Количество учеников должно быть больше нуля"
    ws, records = _class_records()
    for index, row in enumerate(records, start=2):
        if str(row.get("class_name", "")).strip() == class_name:
            ws.update(f"B{index}", [[student_count]], value_input_option="USER_ENTERED")
            logic.log_action("учитель", "численность класса", f"{class_name}: {student_count}")
            return True, f"Для {class_name} сохранено: {student_count} учеников"
    ws.append_row([class_name, student_count, 0, "", 0], value_input_option="USER_ENTERED")
    logic.log_action("учитель", "численность класса", f"{class_name}: {student_count}")
    return True, f"Для {class_name} сохранено: {student_count} учеников"


def _selected_students_by_class():
    achievements_ws = logic.ensure_worksheet("achievements")
    achievement_rows = logic.rows_to_records(logic.safe_get_all_values(achievements_ws))
    submissions = logic.get_submissions()
    class_by_name = {}
    for sub in submissions:
        name = str(sub.get("student_name", "")).strip()
        cls = str(sub.get("student_class", "")).strip()
        if name and cls:
            class_by_name[name] = cls
    selected = {}
    for row in achievement_rows:
        if str(row.get("badge_code", "")).strip() != "topic":
            continue
        name = str(row.get("student_name", "")).strip()
        cls = str(row.get("student_class", "")).strip() or class_by_name.get(name, "")
        if name and cls:
            selected.setdefault(cls, set()).add(name)
    return selected


def get_class_progress(class_name):
    class_name = (class_name or "").strip()
    ws, records = _class_records()
    setting = next((r for r in records if str(r.get("class_name", "")).strip() == class_name), None)
    selected = _selected_students_by_class().get(class_name, set())
    size = 0
    awarded = False
    earned_at = ""
    row_number = None
    if setting:
        try:
            size = int(float(setting.get("student_count", 0) or 0))
        except (TypeError, ValueError):
            size = 0
        awarded = str(setting.get("bonus_awarded", "0")).strip().lower() in ("1", "true", "да", "yes")
        earned_at = str(setting.get("earned_at", "") or "")
        row_number = next((i for i, r in enumerate(records, start=2) if str(r.get("class_name", "")).strip() == class_name), None)
    percent = min(100, int(100 * len(selected) / size)) if size > 0 else 0
    if size > 0 and len(selected) / size >= 0.8 and not awarded and row_number:
        earned_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        ws.update(f"C{row_number}:E{row_number}", [[1, earned_at, len(selected)]], value_input_option="USER_ENTERED")
        logic.log_action("система", "командный значок класса", f"{class_name}: {len(selected)}/{size}")
        awarded = True
    return {
        "class_name": class_name,
        "student_count": size,
        "selected_count": len(selected),
        "percent": percent,
        "configured": size > 0,
        "awarded": awarded,
        "earned_at": earned_at,
    }


def get_class_leaderboard(class_name, limit=10):
    class_name = (class_name or "").strip()
    achievements_ws = logic.ensure_worksheet("achievements")
    records = logic.rows_to_records(logic.safe_get_all_values(achievements_ws))
    submissions = logic.get_submissions()
    class_by_name = {}
    for sub in submissions:
        name = str(sub.get("student_name", "")).strip()
        cls = str(sub.get("student_class", "")).strip()
        if name and cls:
            class_by_name[name] = cls
    totals = {}
    for row in records:
        name = str(row.get("student_name", "")).strip()
        cls = str(row.get("student_class", "")).strip() or class_by_name.get(name, "")
        if not name or cls != class_name:
            continue
        try:
            points = int(float(row.get("points", 0) or 0))
        except (TypeError, ValueError):
            points = 0
        item = totals.setdefault(name, {"student_name": name, "points": 0, "badges": 0})
        item["points"] += points
        item["badges"] += 1
    result = sorted(totals.values(), key=lambda x: (-x["points"], x["student_name"].casefold()))
    for index, item in enumerate(result, start=1):
        item["rank"] = index
    return result[:limit]


def get_teacher_stats():
    topics = logic.get_topics()
    submissions = logic.get_submissions()
    students = {str(t.get("booked_by", "")).strip() for t in topics if t.get("is_booked") == 1 and t.get("booked_by")}
    students.update(str(s.get("student_name", "")).strip() for s in submissions if s.get("student_name"))
    accepted = sum(1 for s in submissions if s.get("status") == "принято")
    revision = sum(1 for s in submissions if s.get("status") == "на доработке")
    pending = sum(1 for s in submissions if s.get("status") == "на проверке")
    settings_ws, settings = _class_records()
    configured_students = 0
    for row in settings:
        try:
            configured_students += int(float(row.get("student_count", 0) or 0))
        except (TypeError, ValueError):
            pass
    return {
        "topics": len(topics),
        "booked_topics": sum(1 for t in topics if t.get("is_booked") == 1),
        "students": len(students),
        "submissions": len(submissions),
        "accepted": accepted,
        "revision": revision,
        "pending": pending,
        "configured_students": configured_students,
    }


def get_project_steps(student_name):
    booking = logic.get_student_booking(student_name)
    submissions = logic.get_student_submissions(student_name)
    achievements = logic.get_student_achievements(student_name)
    earned = {a.get("badge_code") for a in achievements}
    accepted = any(s.get("status") == "принято" for s in submissions)
    submitted = bool(submissions) or "first_submit" in earned
    correction_requested = any("на доработке" in (s.get("status_history") or "") for s in submissions)
    revision_done = submitted and ("revision" in earned or accepted or not correction_requested)
    return [
        {"label": "Тема выбрана", "done": bool(booking), "hint": "Забронируйте тему"},
        {"label": "Работа отправлена", "done": submitted, "hint": "Отправьте первую версию"},
        {"label": "Доработка", "done": revision_done, "hint": "Выполните корректировки, если учитель их назначил"},
        {"label": "Принято", "done": accepted, "hint": "Дождитесь принятия работы"},
    ]


def make_certificate_png(student_name, student_class, topic_title, accepted_at=""):
    width, height = 1600, 1100
    image = Image.new("RGB", (width, height), "#fbf8ef")
    draw = ImageDraw.Draw(image)
    ink = "#26354a"
    gold = "#b58b43"
    draw.rectangle((35, 35, width - 35, height - 35), outline=gold, width=8)
    draw.rectangle((58, 58, width - 58, height - 58), outline=ink, width=2)

    def centered(text, y, font, fill=ink):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)

    centered("СЕРТИФИКАТ", 190, _font(82, True), gold)
    centered("об успешном завершении исследовательского проекта", 310, _font(34))
    centered("Настоящим подтверждается, что", 435, _font(30))
    centered(student_name or "Ученик", 505, _font(62, True))
    centered(f"ученик(ца) класса {student_class}", 595, _font(30))
    centered("успешно выполнил(а) и представил(а) проект:", 680, _font(30))
    title = (topic_title or "Исследовательский проект").strip()
    if len(title) > 70:
        title = title[:67].rstrip() + "..."
    centered(title, 745, _font(38, True))
    centered(f"Дата принятия: {accepted_at or datetime.now().strftime('%d.%m.%Y')}", 865, _font(27))
    centered("Школьный проектный кабинет", 955, _font(25), gold)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
