"""
Create delivery_challans and delivery_challan_items (#840): goods sent to a buyer under
GST Rule 55, on their own tables so that no report, ledger or return can ever read one
as an invoice. A challan moves stock and nothing else.

IF NOT EXISTS throughout: boot runs create_all before migrations, so these tables
usually exist by the time this runs.

Shared hosting: boot applies the row-level security policies to both tables
(src/db/rls.py). The app role's grants come from ALTER DEFAULT PRIVILEGES, and the
boot check refuses to start if they are missing.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS delivery_challans (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES company_profiles(id),
            challan_number VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL,
            purpose VARCHAR(32) NOT NULL,
            challan_date DATE NOT NULL,
            financial_year_id INTEGER REFERENCES financial_years(id),
            ledger_id INTEGER NOT NULL REFERENCES buyers(id),
            ledger_name VARCHAR,
            ledger_address VARCHAR,
            ledger_gst VARCHAR,
            ledger_phone VARCHAR,
            company_name VARCHAR,
            company_address VARCHAR,
            company_gst VARCHAR,
            company_phone VARCHAR,
            company_email VARCHAR,
            company_website VARCHAR,
            company_currency_code VARCHAR,
            company_bank_name VARCHAR,
            company_branch_name VARCHAR,
            company_account_name VARCHAR,
            company_account_number VARCHAR,
            company_ifsc_code VARCHAR,
            company_logo_data TEXT,
            company_logo_mime_type VARCHAR(50),
            company_additional_info TEXT,
            company_terms_text TEXT,
            place_of_supply VARCHAR(2),
            shipping_address TEXT,
            shipping_address_label VARCHAR(255),
            shipping_address_id INTEGER REFERENCES ledger_addresses(id) ON DELETE SET NULL,
            reference_notes VARCHAR,
            terms_text TEXT,
            taxable_amount NUMERIC(10, 2) NOT NULL,
            total_tax_amount NUMERIC(10, 2) NOT NULL,
            cgst_amount NUMERIC(10, 2) NOT NULL,
            sgst_amount NUMERIC(10, 2) NOT NULL,
            igst_amount NUMERIC(10, 2) NOT NULL,
            total_amount NUMERIC(10, 2) NOT NULL,
            invoiced_at TIMESTAMP,
            cancelled_at TIMESTAMP,
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            CONSTRAINT uq_delivery_challans_company_number UNIQUE (company_id, challan_number)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_delivery_challans_id ON delivery_challans (id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_delivery_challans_ledger_id ON delivery_challans (ledger_id)"))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_delivery_challans_company_status ON delivery_challans (company_id, status)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_delivery_challans_company_date ON delivery_challans (company_id, challan_date)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS delivery_challan_items (
            id SERIAL PRIMARY KEY,
            challan_id INTEGER NOT NULL REFERENCES delivery_challans(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            hsn_sac VARCHAR,
            quantity NUMERIC(12, 3) NOT NULL,
            unit_price NUMERIC(10, 2) NOT NULL,
            gst_rate NUMERIC(5, 2) NOT NULL,
            taxable_amount NUMERIC(10, 2) NOT NULL,
            tax_amount NUMERIC(10, 2) NOT NULL,
            cgst_amount NUMERIC(10, 2) NOT NULL,
            sgst_amount NUMERIC(10, 2) NOT NULL,
            igst_amount NUMERIC(10, 2) NOT NULL,
            line_total NUMERIC(10, 2) NOT NULL,
            description TEXT
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_delivery_challan_items_id ON delivery_challan_items (id)"))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_delivery_challan_items_challan_id ON delivery_challan_items (challan_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_delivery_challan_items_product_id ON delivery_challan_items (product_id)"
    ))


def down(conn) -> None:
    conn.execute(text("DROP TABLE IF EXISTS delivery_challan_items"))
    conn.execute(text("DROP TABLE IF EXISTS delivery_challans"))
