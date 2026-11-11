-- Independent SQL model for comparing one diagnostic report with a MongoDB document.
-- Mapping to Lab 1: hospital.lab_order -> lab2.report;
-- hospital.lab_order_item + hospital.lab_test -> lab2.panel + lab2.measurement + lab2.test_catalog.
CREATE SCHEMA IF NOT EXISTS lab2;
CREATE TABLE lab2.report (
  id text PRIMARY KEY,
  patient_id text NOT NULL,
  source_encounter_id bigint,
  collected_at timestamptz NOT NULL,
  status text NOT NULL CHECK (status IN ('final','amended')),
  CHECK (length(id)>0 AND length(patient_id)>0)
);
CREATE TABLE lab2.panel (
  report_id text NOT NULL REFERENCES lab2.report(id) ON DELETE CASCADE,
  code text NOT NULL,
  PRIMARY KEY (report_id, code)
);
CREATE TABLE lab2.test_catalog (
  panel_code text NOT NULL,
  test_code text NOT NULL,
  display_name text NOT NULL,
  unit text NOT NULL,
  PRIMARY KEY (panel_code, test_code)
);
CREATE TABLE lab2.measurement (
  report_id text NOT NULL,
  panel_code text NOT NULL,
  test_code text NOT NULL,
  value_num numeric(12,3) NOT NULL,
  reference_low numeric(12,3) NOT NULL,
  reference_high numeric(12,3) NOT NULL,
  PRIMARY KEY (report_id, panel_code, test_code),
  FOREIGN KEY (report_id, panel_code)
    REFERENCES lab2.panel(report_id, code) ON DELETE CASCADE,
  FOREIGN KEY (panel_code, test_code)
    REFERENCES lab2.test_catalog(panel_code, test_code),
  CHECK (reference_low <= reference_high)
);
CREATE INDEX ix_report_patient_date ON lab2.report(patient_id, collected_at DESC, id DESC);
CREATE INDEX ix_measurement_test ON lab2.measurement(test_code, report_id);
COMMENT ON TABLE lab2.report IS 'One diagnostic report; extension of Lab 1 lab_order.';
COMMENT ON TABLE lab2.measurement IS 'One numeric test result with historical reference limits.';
