# Сервис бронирования тем исследовательских проектов

Streamlit-приложение для школы.  
Темы и работы учеников **постоянно** хранятся в Google Таблицах и Google Диске.

## Возможности

### Ученик
- Выбор класса и просмотр свободных тем
- Бронирование темы
- Загрузка файла работы (сохраняется в Google Drive)
- Просмотр статуса и комментариев учителя

### Учитель
- Просмотр и скачивание работ (ссылка на Google Drive)
- Статусы: принято / на доработку
- Добавление, редактирование и удаление тем
- Статистика

## Настройка Google (один раз)

### 1. Создайте Service Account

1. Откройте [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте проект (или выберите существующий)
3. Перейдите в **APIs & Services → Library**
4. Включите:
   - Google Sheets API
   - Google Drive API
5. Перейдите в **APIs & Services → Credentials**
6. **Create Credentials → Service Account**
7. Дайте имя (например `streamlit-topics`)
8. После создания нажмите на аккаунт → вкладка **Keys → Add Key → Create new key → JSON**
9. Скачается файл JSON — сохраните его.

### 2. Создайте Google Таблицу и папку на Диске

1. Создайте новую Google Таблицу (название любое, например «Темы проектов»)
2. Скопируйте **ID таблицы** из адресной строки:
   `https://docs.google.com/spreadsheets/d/ВОТ_ЭТОТ_ID/edit`
3. Создайте папку на Google Диске (например «Работы учеников»)
4. Откройте папку → URL будет вида:
   `https://drive.google.com/drive/folders/ВОТ_ЭТОТ_ID`
5. **Важно:** откройте таблицу и папку → Настройки доступа → Добавьте email сервисного аккаунта (из JSON, поле `client_email`) с правами **Редактор**.

### 3. Настройте Secrets в Streamlit Cloud

1. Откройте ваше приложение на [share.streamlit.io](https://share.streamlit.io)
2. Settings → Secrets
3. Вставьте следующее (замените значения):

```toml
SPREADSHEET_ID = "ваш_id_таблицы"
DRIVE_FOLDER_ID = "ваш_id_папки"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

Скопируйте все поля из скачанного JSON-файла в секцию `[gcp_service_account]`.

4. Сохраните Secrets и перезапустите приложение.

## Локальный запуск

```bash
pip install -r requirements.txt
streamlit run app.py
```

Для локального запуска создайте файл `.streamlit/secrets.toml` с теми же данными.

## Пароль учителя

По умолчанию: `teacher2026`  
Смените в `app.py` (переменная `TEACHER_PASSWORD`).

## Структура данных в Google Таблице

Приложение само создаст два листа:

- **topics** — темы проектов
- **submissions** — сданные работы (со ссылками на файлы в Drive)
