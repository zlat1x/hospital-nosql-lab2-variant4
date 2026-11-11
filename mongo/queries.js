const reports = db.getSiblingDB("hospital_lab2").reports;

print("Q1. Report with nested panels/measurements:");
printjson(reports.findOne({ _id: "R00000001" }));

print("Q2. Last 10 IDs of a patient:");
printjson(reports.find({ patient_id: "DEMO-P00001" }, { _id: 1 })
  .sort({ collected_at: -1, _id: -1 }).limit(10).toArray());

print("Q3. Count abnormal measurements:");
printjson(reports.aggregate([
  { $match: { patient_id: "DEMO-P00001" } },
  { $unwind: "$panels" },
  { $unwind: "$panels.measurements" },
  { $match: { $expr: { $or: [
    { $lt: ["$panels.measurements.value", "$panels.measurements.reference_low"] },
    { $gt: ["$panels.measurements.value", "$panels.measurements.reference_high"] }
  ] } } },
  { $count: "abnormal_count" }
]).toArray());

print("Q4. Last 20 glucose measurements:");
printjson(reports.aggregate([
  { $match: { patient_id: "DEMO-P00001", "panels.measurements.code": "GLU" } },
  { $unwind: "$panels" }, { $unwind: "$panels.measurements" },
  { $match: { "panels.measurements.code": "GLU" } },
  { $sort: { collected_at: -1, _id: -1 } }, { $limit: 20 },
  { $project: { report_id: "$_id", collected_at: 1,
                value: "$panels.measurements.value", _id: 0 } }
]).toArray());

print("Q5. Find query plan:");
printjson(reports.find({ patient_id: "DEMO-P00001" }, { _id: 1 })
  .sort({ collected_at: -1, _id: -1 }).limit(10).explain("queryPlanner").queryPlanner);
