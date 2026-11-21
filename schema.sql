PRAGMA foreign_keys = ON;

CREATE TABLE hospitals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  city TEXT NOT NULL,
  phone TEXT,
  address TEXT
);

CREATE TABLE doctors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hospital_id INTEGER NOT NULL REFERENCES hospitals(id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  specialization TEXT NOT NULL,
  phone TEXT,
  email TEXT UNIQUE
);

CREATE TABLE patients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  dob DATE NOT NULL,
  gender TEXT CHECK (gender IN ('Male','Female','Other')),
  blood_group TEXT,
  phone TEXT,
  address TEXT,
  allergies TEXT,
  emergency_contact TEXT
);

CREATE TABLE medical_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE RESTRICT,
  visit_date DATE NOT NULL,
  complaint TEXT NOT NULL,
  bp TEXT,
  pulse INTEGER,
  temperature REAL,
  weight REAL,
  diagnosis TEXT NOT NULL,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Follow-up','Resolved')),
  follow_up_date DATE,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE prescriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id INTEGER NOT NULL REFERENCES medical_records(id) ON DELETE CASCADE,
  medicine TEXT NOT NULL,
  dosage TEXT,
  frequency TEXT,
  duration TEXT
);

CREATE TABLE reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id INTEGER NOT NULL REFERENCES medical_records(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  filename TEXT NOT NULL,
  original_name TEXT NOT NULL,
  uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_doctors_hospital ON doctors(hospital_id);
CREATE INDEX idx_records_patient ON medical_records(patient_id);
CREATE INDEX idx_records_doctor ON medical_records(doctor_id);
CREATE INDEX idx_rx_record ON prescriptions(record_id);
CREATE INDEX idx_reports_record ON reports(record_id);
