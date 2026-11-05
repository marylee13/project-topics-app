import streamlit as st

TEACHER_PASSWORD = "marylee_13"
BADGES = {}
LEVELS = [{"level": 1, "min_points": 0, "title": "Новичок", "icon": "🌱"}]

def init_sheets():
    return True

def get_topics_cached():
    return []

def get_topics(grade=None, only_free=False, search=None):
    return []

def get_student_booking(student_name):
    return None

def book_topic(*a, **k):
    return False, "Идёт техническое обновление. Подождите несколько минут и обновите страницу."

def unbook_topic(*a, **k):
    return False, "Идёт техническое обновление."

def delete_topic(*a, **k):
    pass

def update_topic(*a, **k):
    pass

def add_topic(*a, **k):
    return 0

def add_topics_bulk(rows):
    return 0

def get_materials():
    return []

def add_material(*a, **k):
    raise RuntimeError("Идёт обновление")

def add_material_by_link(*a, **k):
    raise RuntimeError("Идёт обновление")

def delete_material(*a, **k):
    pass

def submit_work(*a, **k):
    return False, "Идёт техническое обновление."

def get_submissions(*a, **k):
    return []

def update_submission_status(*a, **k):
    pass

def get_student_submissions(*a, **k):
    return []

def get_action_log(limit=100):
    return []

def topics_to_csv(topics):
    return ""

def submissions_to_csv(subs):
    return ""

def log_action(*a, **k):
    pass

def add_question(*a, **k):
    return False, "Идёт обновление"

def get_questions(*a, **k):
    return []

def answer_question(*a, **k):
    return False, "Идёт обновление"

def mark_question_status(*a, **k):
    return False, "Идёт обновление"

def add_announcement(*a, **k):
    return False, "Идёт обновление"

def get_announcements(*a, **k):
    return []

def update_announcement(*a, **k):
    return False, "Идёт обновление"

def set_announcement_active(*a, **k):
    return False, "Идёт обновление"

def delete_announcement(*a, **k):
    return False, "Идёт обновление"

def get_student_achievements(*a, **k):
    return []

def get_badge_progress(*a, **k):
    return []

def get_student_points(*a, **k):
    return 0

def get_student_level(*a, **k):
    return {"points": 0, "level": 1, "title": "Новичок", "icon": "🌱", "next_level": None, "next_title": None, "next_icon": None, "points_to_next": 0, "progress_pct": 0}

def get_next_steps(*a, **k):
    return []

def teacher_award_badge(*a, **k):
    return False, "Идёт обновление"

def get_class_leaderboard(*a, **k):
    return []

def get_teacher_stats():
    return {"total_topics": 0, "booked": 0, "free": 0, "submissions_total": 0, "status": {}, "achievements_total": 0, "students_with_badges": 0, "badge_counts": {}, "questions_total": 0, "questions_new": 0}
