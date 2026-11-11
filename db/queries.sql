-- PostgreSQL equivalents of the MongoDB read workloads.

-- Q1. Rebuild the complete report from FOUR relational tables.
SELECT r.id, r.patient_id, r.collected_at, r.status,
       p.code AS panel_code, m.test_code, c.display_name, c.unit,
       m.value_num, m.reference_low, m.reference_high
FROM lab2.report r
JOIN lab2.panel p ON p.report_id = r.id
JOIN lab2.measurement m ON (m.report_id, m.panel_code) = (p.report_id, p.code)
JOIN lab2.test_catalog c ON (c.panel_code, c.test_code) = (m.panel_code, m.test_code)
WHERE r.id = 'R00000001'
ORDER BY p.code, m.test_code;

-- Q2. Last 10 report IDs for a chosen patient.
SELECT id FROM lab2.report WHERE patient_id = 'DEMO-P00001'
ORDER BY collected_at DESC, id DESC LIMIT 10;

-- Q3. Count abnormal measurements in this patient's entire history.
SELECT count(*) AS abnormal_count FROM lab2.report r
JOIN lab2.measurement m ON m.report_id = r.id
WHERE r.patient_id = 'DEMO-P00001'
AND (m.value_num < m.reference_low OR m.value_num > m.reference_high);

-- Q4. Last 20 glucose values for the patient.
SELECT r.id, r.collected_at, m.value_num FROM lab2.report r
JOIN lab2.measurement m ON m.report_id = r.id
WHERE r.patient_id = 'DEMO-P00001' AND m.test_code = 'GLU'
ORDER BY r.collected_at DESC, r.id DESC LIMIT 20;

-- Q5. Inspect the plan; EXPLAIN ANALYZE executes the SELECT (no write).
EXPLAIN (ANALYZE, BUFFERS)
SELECT id FROM lab2.report WHERE patient_id = 'DEMO-P00001'
ORDER BY collected_at DESC, id DESC LIMIT 10;
