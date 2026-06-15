-- Schema fuer Suite8 XRechnung MiniApp (Initial Migration)

CREATE TABLE invoices (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  zinv_id           INTEGER NOT NULL,
  zinv_number       TEXT    NOT NULL,
  zinv_date         TEXT    NOT NULL,
  zinv_role         INTEGER NOT NULL,
  invoice_type      TEXT    NOT NULL,

  customer_name     TEXT,
  customer_zip      TEXT,
  customer_city     TEXT,
  customer_country  TEXT,
  buyer_reference   TEXT,

  amount_net        REAL,
  amount_tax        REAL,
  amount_gross      REAL,
  currency          TEXT,

  status            TEXT NOT NULL,
  xml_path          TEXT,
  xml_hash          TEXT,
  recipient_email   TEXT,
  sent_at           TEXT,
  graph_message_id  TEXT,
  re_send_count     INTEGER DEFAULT 0,

  retry_count       INTEGER DEFAULT 0,
  next_retry_at     TEXT,
  last_error        TEXT,

  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
  created_by        TEXT NOT NULL,

  UNIQUE (zinv_id)
);

CREATE INDEX idx_invoices_status        ON invoices(status);
CREATE INDEX idx_invoices_zinv_number   ON invoices(zinv_number);
CREATE INDEX idx_invoices_zinv_date     ON invoices(zinv_date);
CREATE INDEX idx_invoices_customer_name ON invoices(customer_name);
CREATE INDEX idx_invoices_next_retry    ON invoices(next_retry_at) WHERE next_retry_at IS NOT NULL;

CREATE TABLE queue_issues (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id   INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  field        TEXT    NOT NULL,
  severity     TEXT    NOT NULL,
  message      TEXT    NOT NULL,
  resolution   TEXT,
  resolved_at  TEXT,
  resolved_by  TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_queue_invoice ON queue_issues(invoice_id);
CREATE INDEX idx_queue_open    ON queue_issues(resolved_at) WHERE resolved_at IS NULL;

CREATE TABLE invoice_overrides (
  invoice_id  INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  field       TEXT    NOT NULL,
  value       TEXT    NOT NULL,
  set_by      TEXT    NOT NULL,
  set_at      TEXT    NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (invoice_id, field)
);

CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL DEFAULT (datetime('now')),
  user        TEXT NOT NULL,
  action      TEXT NOT NULL,
  invoice_id  INTEGER,
  details     TEXT
);

CREATE INDEX idx_audit_ts    ON audit_log(ts);
CREATE INDEX idx_audit_user  ON audit_log(user);
