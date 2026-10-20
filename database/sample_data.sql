USE hostel_management;

INSERT INTO users (full_name, email, password_hash, role) VALUES
('Farhan Wajid', 'admin@hostel.local', '$argon2id$v=19$m=65536,t=3,p=4$synthetic-admin-hash', 'administrator'),
('Rahul Verma', 'rahul@hostel.local', '$argon2id$v=19$m=65536,t=3,p=4$synthetic-resident-hash', 'resident'),
('Meera Singh', 'meera@hostel.local', '$argon2id$v=19$m=65536,t=3,p=4$synthetic-resident-hash', 'resident'),
('Imran Ali', 'imran@hostel.local', '$argon2id$v=19$m=65536,t=3,p=4$synthetic-staff-hash', 'maintenance_staff');

INSERT INTO residents (user_id, roll_number, full_name, email, phone, course, academic_year, eligibility_status) VALUES
(2, '101', 'Rahul Verma', 'rahul@hostel.local', '9000000001', 'Computer Science', 3, 'eligible'),
(3, '102', 'Meera Singh', 'meera@hostel.local', '9000000002', 'Computer Science', 2, 'eligible');

INSERT INTO hostels (name, location, description) VALUES
('Hostel Block A', 'North Campus', 'Undergraduate residence'),
('Hostel Block B', 'South Campus', 'Mixed residence');

INSERT INTO rooms (hostel_id, room_number, floor, room_type) VALUES
(1, '101', 1, 'double'), (1, '102', 1, 'double'), (2, '201', 2, 'triple');

INSERT INTO beds (room_id, bed_number, status) VALUES
(1, 'A', 'available'), (1, 'B', 'available'),
(2, 'A', 'available'), (2, 'B', 'maintenance'),
(3, 'A', 'available'), (3, 'B', 'available'), (3, 'C', 'available');

INSERT INTO allocations (resident_id, bed_id, allocated_by, start_date)
VALUES (1, 1, 1, '2026-07-01');

INSERT INTO complaints
  (resident_id, room_id, bed_id, assigned_to, category, subject, description, priority, status)
VALUES
(1, 1, 1, 4, 'electrical', 'Study light not working', 'The light near the study table is not switching on.', 'high', 'assigned'),
(2, 1, NULL, NULL, 'plumbing', 'Washbasin tap leaking', 'Water leaks continuously from the tap.', 'medium', 'open');

INSERT INTO complaint_updates (complaint_id, changed_by, old_status, new_status, remark)
VALUES (1, 1, 'open', 'assigned', 'Assigned to maintenance staff.');

INSERT INTO fee_invoices (resident_id, fee_period, amount_due, due_date)
VALUES (1, '2026-07', 25000.00, '2026-07-10'), (2, '2026-07', 25000.00, '2026-07-10');

INSERT INTO payments (invoice_id, recorded_by, amount, payment_reference)
VALUES (1, 1, 15000.00, 'PAY-SYNTH-0001');

INSERT INTO notifications (user_id, title, message)
VALUES (2, 'Allocation confirmed', 'Your bed allocation for room 101 is active.');
