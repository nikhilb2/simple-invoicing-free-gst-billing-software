"""
add_default_pdf_paper_to_company_profiles

The paper a company's PDFs are laid out for when a print does not choose one:
A4, A5, or an 80mm or 58mm thermal roll.
"""

from sqlalchemy import text


def up(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_profiles
        ADD COLUMN IF NOT EXISTS default_pdf_paper VARCHAR(16) NOT NULL DEFAULT 'a4'
    """))
    conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_company_profiles_default_pdf_paper'
            ) THEN
                ALTER TABLE company_profiles
                ADD CONSTRAINT ck_company_profiles_default_pdf_paper
                CHECK (default_pdf_paper IN ('a4', 'a5', 'thermal80', 'thermal58'));
            END IF;
        END $$;
    """))


def down(conn) -> None:
    conn.execute(text("""
        ALTER TABLE company_profiles
        DROP CONSTRAINT IF EXISTS ck_company_profiles_default_pdf_paper
    """))
    conn.execute(text("""
        ALTER TABLE company_profiles
        DROP COLUMN IF EXISTS default_pdf_paper
    """))
