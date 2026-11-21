# Carebook: Health Record Management System

Stack: HTML, CSS, vanilla JavaScript, Python Flask, SQLite (raw SQL, no ORM).

## Run it
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000. The first run creates `health.db` from `schema.sql` and loads sample data
(3 hospitals, 4 doctors, 6 patients, 8 records). To reset, delete `health.db` and run again.

## Notes
- No login: pick Administrator, Doctor or Patient on the home page. Use "switch role" in the top bar.
- Uploads (PDF, PNG, JPG, max 8 MB) are saved in `uploads/` with random names.
- Change `app.secret_key` in `app.py` before showing this to anyone outside class.
