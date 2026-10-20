USE hostel_management;

-- Occupancy by hostel, including hostels with no rooms.
SELECT h.name AS hostel,
       COUNT(b.id) AS total_beds,
       SUM(b.status = 'available') AS available_beds,
       SUM(b.status = 'maintenance') AS maintenance_beds,
       COUNT(a.id) AS occupied_beds
FROM hostels h
LEFT JOIN rooms r ON r.hostel_id = h.id AND r.is_active = TRUE
LEFT JOIN beds b ON b.room_id = r.id
LEFT JOIN allocations a ON a.bed_id = b.id AND a.status = 'active'
GROUP BY h.id, h.name
ORDER BY h.name;

-- Complaint priority distribution.
SELECT priority, status, COUNT(*) AS complaint_count
FROM complaints
GROUP BY priority, status
ORDER BY FIELD(priority, 'urgent', 'high', 'medium', 'low'), status;

-- Residents currently allocated, with room and hostel.
SELECT res.roll_number, res.full_name, h.name AS hostel, r.room_number,
       b.bed_number, a.start_date
FROM allocations a
JOIN residents res ON res.id = a.resident_id
JOIN beds b ON b.id = a.bed_id
JOIN rooms r ON r.id = b.room_id
JOIN hostels h ON h.id = r.hostel_id
WHERE a.status = 'active'
ORDER BY h.name, r.room_number, b.bed_number;

-- Residents with no active allocation (EXISTS / NOT EXISTS).
SELECT res.id, res.roll_number, res.full_name
FROM residents res
WHERE res.is_active = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM allocations a
    WHERE a.resident_id = res.id AND a.status = 'active'
  );

-- Outstanding balances and overdue invoices.
SELECT i.id, res.roll_number, res.full_name, i.fee_period, i.amount_due,
       COALESCE(SUM(p.amount), 0) AS paid,
       i.amount_due - COALESCE(SUM(p.amount), 0) AS outstanding,
       i.due_date
FROM fee_invoices i
JOIN residents res ON res.id = i.resident_id
LEFT JOIN payments p ON p.invoice_id = i.id
WHERE i.status <> 'cancelled'
GROUP BY i.id, res.roll_number, res.full_name, i.fee_period, i.amount_due, i.due_date
HAVING outstanding > 0
ORDER BY i.due_date;

-- Allocation history, including completed/cancelled allocations.
SELECT res.roll_number, res.full_name, h.name AS hostel, r.room_number,
       b.bed_number, a.start_date, a.end_date, a.status
FROM allocations a
JOIN residents res ON res.id = a.resident_id
JOIN beds b ON b.id = a.bed_id
JOIN rooms r ON r.id = b.room_id
JOIN hostels h ON h.id = r.hostel_id
ORDER BY res.roll_number, a.start_date DESC;

-- Average resolution time in hours.
SELECT AVG(TIMESTAMPDIFF(HOUR, submitted_at, resolved_at)) AS avg_resolution_hours
FROM complaints
WHERE resolved_at IS NOT NULL;
