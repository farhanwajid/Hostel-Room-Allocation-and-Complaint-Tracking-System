CREATE DATABASE IF NOT EXISTS hostel_management
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
USE hostel_management;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS activity_logs, notifications, payments, fee_invoices,
  complaint_updates, complaints, room_transfers, allocations, beds, rooms,
  hostels, residents, users;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE users (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(120) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('administrator', 'resident', 'maintenance_staff') NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_users_role_active (role, is_active)
) ENGINE=InnoDB;

CREATE TABLE residents (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id INT UNSIGNED NULL UNIQUE,
  roll_number VARCHAR(40) NOT NULL UNIQUE,
  full_name VARCHAR(120) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  phone VARCHAR(30) NULL,
  course VARCHAR(120) NOT NULL,
  academic_year TINYINT UNSIGNED NOT NULL,
  eligibility_status ENUM('eligible', 'ineligible', 'pending') NOT NULL DEFAULT 'pending',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT chk_resident_year CHECK (academic_year BETWEEN 1 AND 8),
  CONSTRAINT fk_residents_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_residents_search (full_name, roll_number, eligibility_status)
) ENGINE=InnoDB;

CREATE TABLE hostels (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE,
  location VARCHAR(255) NOT NULL,
  description VARCHAR(500) NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE rooms (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  hostel_id INT UNSIGNED NOT NULL,
  room_number VARCHAR(20) NOT NULL,
  floor SMALLINT NOT NULL,
  room_type ENUM('single', 'double', 'triple', 'quad', 'other') NOT NULL,
  monthly_amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_rooms_hostel_number (hostel_id, room_number),
  CONSTRAINT fk_rooms_hostel FOREIGN KEY (hostel_id) REFERENCES hostels(id),
  INDEX idx_rooms_filter (hostel_id, floor, room_type)
) ENGINE=InnoDB;

CREATE TABLE beds (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  room_id INT UNSIGNED NOT NULL,
  bed_number VARCHAR(20) NOT NULL,
  status ENUM('available', 'maintenance', 'retired') NOT NULL DEFAULT 'available',
  monthly_amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_beds_room_number (room_id, bed_number),
  CONSTRAINT fk_beds_room FOREIGN KEY (room_id) REFERENCES rooms(id),
  INDEX idx_beds_status (status, room_id)
) ENGINE=InnoDB;

CREATE TABLE allocations (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  resident_id INT UNSIGNED NOT NULL,
  bed_id INT UNSIGNED NOT NULL,
  allocated_by INT UNSIGNED NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NULL,
  monthly_amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
  status ENUM('active', 'completed', 'cancelled') NOT NULL DEFAULT 'active',
  cancellation_reason VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  active_resident_key INT UNSIGNED GENERATED ALWAYS AS
    (IF(status = 'active', resident_id, NULL)) STORED,
  active_bed_key INT UNSIGNED GENERATED ALWAYS AS
    (IF(status = 'active', bed_id, NULL)) STORED,
  UNIQUE KEY uq_allocations_active_resident (active_resident_key),
  UNIQUE KEY uq_allocations_active_bed (active_bed_key),
  CONSTRAINT chk_allocation_dates CHECK (end_date IS NULL OR end_date >= start_date),
  CONSTRAINT fk_allocations_resident FOREIGN KEY (resident_id) REFERENCES residents(id),
  CONSTRAINT fk_allocations_bed FOREIGN KEY (bed_id) REFERENCES beds(id),
  CONSTRAINT fk_allocations_admin FOREIGN KEY (allocated_by) REFERENCES users(id),
  INDEX idx_allocations_history (resident_id, start_date, status),
  INDEX idx_allocations_bed_history (bed_id, start_date, status)
) ENGINE=InnoDB;

CREATE TABLE room_transfers (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  resident_id INT UNSIGNED NOT NULL,
  from_allocation_id INT UNSIGNED NOT NULL,
  to_allocation_id INT UNSIGNED NOT NULL,
  reason VARCHAR(500) NOT NULL,
  transferred_by INT UNSIGNED NOT NULL,
  transferred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_transfers_resident FOREIGN KEY (resident_id) REFERENCES residents(id),
  CONSTRAINT fk_transfers_from FOREIGN KEY (from_allocation_id) REFERENCES allocations(id),
  CONSTRAINT fk_transfers_to FOREIGN KEY (to_allocation_id) REFERENCES allocations(id),
  CONSTRAINT fk_transfers_admin FOREIGN KEY (transferred_by) REFERENCES users(id),
  CONSTRAINT chk_transfer_allocations CHECK (from_allocation_id <> to_allocation_id),
  INDEX idx_transfers_resident_date (resident_id, transferred_at)
) ENGINE=InnoDB;

CREATE TABLE complaints (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  resident_id INT UNSIGNED NOT NULL,
  room_id INT UNSIGNED NULL,
  bed_id INT UNSIGNED NULL,
  assigned_to INT UNSIGNED NULL,
  category ENUM('electrical', 'plumbing', 'cleaning', 'furniture', 'internet', 'security', 'other') NOT NULL,
  subject VARCHAR(180) NOT NULL,
  description TEXT NOT NULL,
  priority ENUM('low', 'medium', 'high', 'urgent') NOT NULL DEFAULT 'medium',
  status ENUM('open', 'assigned', 'in_progress', 'resolved', 'closed') NOT NULL DEFAULT 'open',
  submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_complaints_resident FOREIGN KEY (resident_id) REFERENCES residents(id),
  CONSTRAINT fk_complaints_room FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE SET NULL,
  CONSTRAINT fk_complaints_bed FOREIGN KEY (bed_id) REFERENCES beds(id) ON DELETE SET NULL,
  CONSTRAINT fk_complaints_assignee FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_complaints_queue (status, priority, submitted_at),
  INDEX idx_complaints_resident (resident_id, submitted_at)
) ENGINE=InnoDB;

CREATE TABLE complaint_updates (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  complaint_id INT UNSIGNED NOT NULL,
  changed_by INT UNSIGNED NOT NULL,
  old_status ENUM('open', 'assigned', 'in_progress', 'resolved', 'closed') NULL,
  new_status ENUM('open', 'assigned', 'in_progress', 'resolved', 'closed') NOT NULL,
  remark TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_updates_complaint FOREIGN KEY (complaint_id) REFERENCES complaints(id) ON DELETE CASCADE,
  CONSTRAINT fk_updates_user FOREIGN KEY (changed_by) REFERENCES users(id),
  INDEX idx_updates_complaint_date (complaint_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE fee_invoices (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  resident_id INT UNSIGNED NOT NULL,
  fee_period VARCHAR(30) NOT NULL,
  amount_due DECIMAL(12, 2) NOT NULL,
  due_date DATE NOT NULL,
  status ENUM('unpaid', 'partially_paid', 'paid', 'overdue', 'cancelled') NOT NULL DEFAULT 'unpaid',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_invoice_period (resident_id, fee_period),
  CONSTRAINT chk_invoice_amount CHECK (amount_due > 0),
  CONSTRAINT fk_invoices_resident FOREIGN KEY (resident_id) REFERENCES residents(id),
  INDEX idx_invoices_status_due (status, due_date)
) ENGINE=InnoDB;

CREATE TABLE payments (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  invoice_id INT UNSIGNED NOT NULL,
  recorded_by INT UNSIGNED NOT NULL,
  amount DECIMAL(12, 2) NOT NULL,
  payment_reference VARCHAR(80) NOT NULL UNIQUE,
  paid_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_payment_amount CHECK (amount > 0),
  CONSTRAINT fk_payments_invoice FOREIGN KEY (invoice_id) REFERENCES fee_invoices(id),
  CONSTRAINT fk_payments_user FOREIGN KEY (recorded_by) REFERENCES users(id),
  INDEX idx_payments_invoice_date (invoice_id, paid_at)
) ENGINE=InnoDB;

CREATE TABLE notifications (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id INT UNSIGNED NOT NULL,
  title VARCHAR(160) NOT NULL,
  message VARCHAR(500) NOT NULL,
  is_read BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_notifications_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_notifications_user_read (user_id, is_read, created_at)
) ENGINE=InnoDB;

CREATE TABLE activity_logs (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id INT UNSIGNED NULL,
  action VARCHAR(100) NOT NULL,
  entity_type VARCHAR(60) NOT NULL,
  entity_id INT UNSIGNED NULL,
  details JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_activity_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_activity_entity (entity_type, entity_id, created_at),
  INDEX idx_activity_user_date (user_id, created_at)
) ENGINE=InnoDB;

DELIMITER //
CREATE TRIGGER trg_allocation_bed_available
BEFORE INSERT ON allocations
FOR EACH ROW
BEGIN
  IF NEW.status = 'active' AND EXISTS (
    SELECT 1 FROM beds WHERE id = NEW.bed_id AND status <> 'available'
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only available beds can be actively allocated';
  END IF;
END//
CREATE TRIGGER trg_payment_not_overpay
BEFORE INSERT ON payments
FOR EACH ROW
BEGIN
  DECLARE invoice_total DECIMAL(12,2);
  DECLARE paid_total DECIMAL(12,2);
  SELECT amount_due INTO invoice_total FROM fee_invoices WHERE id = NEW.invoice_id;
  SELECT COALESCE(SUM(amount), 0) INTO paid_total FROM payments WHERE invoice_id = NEW.invoice_id;
  IF invoice_total IS NULL OR paid_total + NEW.amount > invoice_total THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Payment exceeds invoice balance';
  END IF;
END//
DELIMITER ;
