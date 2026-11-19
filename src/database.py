import os
from typing import List, Dict
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Încarcă variabilele secrete (parola, userul, portul) din fișierul .env în memoria sistemului
load_dotenv()


def get_connection(db_name: str = None):
    """
    Creează și returnează o conexiune activă către serverul PostgreSQL.
    RealDictCursor face ca rezultatele interogărilor să vină sub formă de dicționare
    (ex: row['name'] în loc de tuple gen row[2]), fiind mult mai ușor de citit.
    """
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=db_name or os.getenv("DB_NAME", "erp_inventory"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
        cursor_factory=RealDictCursor,
    )


def init_db(db_name: str = None) -> None:
    """
    Creează tabelele în baza de date dacă nu există deja.
    Folosim constrângeri SQL (CHECK, UNIQUE, FOREIGN KEY) ca ultimă linie de apărare
    împotriva datelor corupte, chiar dacă cineva modifică baza direct din pgAdmin.
    """
    conn = get_connection(db_name)
    try:
        # Blocul 'with conn:' deschide o tranzacție: dacă totul merge bine face COMMIT automat,
        # iar dacă apare vreo eroare face ROLLBACK (anulează modificările).
        with conn:
            with conn.cursor() as cur:
                # 1. Tabelul nomenclatorului de produse
                # SERIAL = ID auto-incrementat specific PostgreSQL
                # NUMERIC(10, 2) = stochează bani cu 2 zecimale exacte (evită erorile de rotunjire ale lui FLOAT)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS products (
                        id SERIAL PRIMARY KEY,
                        sku VARCHAR(50) UNIQUE NOT NULL,
                        name VARCHAR(150) NOT NULL,
                        unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
                        current_stock INTEGER NOT NULL DEFAULT 0 CHECK (current_stock >= 0),
                        min_threshold INTEGER NOT NULL DEFAULT 5 CHECK (min_threshold >= 0)
                    );
                """)

                # 2. Tabelul istoricului mișcărilor (intrări/ieșiri)
                # REFERENCES products(id) ON DELETE CASCADE = leagă mișcarea de un produs existent;
                # dacă se șterge produsul, se șterg și mișcările lui.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS stock_movements (
                        id SERIAL PRIMARY KEY,
                        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                        movement_type VARCHAR(10) NOT NULL CHECK (movement_type IN ('IN', 'OUT')),
                        quantity INTEGER NOT NULL CHECK (quantity > 0),
                        note TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
    finally:
        # Închidem mereu conexiunea în blocul 'finally' pentru a nu lăsa conexiuni blocate pe server
        conn.close()


def add_product(
    sku: str,
    name: str,
    unit_price: float,
    initial_stock: int,
    min_threshold: int,
    db_name: str = None,
) -> int:
    """
    Adaugă un produs nou în nomenclator și, dacă are stoc inițial > 0,
    înregistrează automat o primă mișcare de tip 'IN' în istoric.
    """
    # Validări la nivel de aplicație înainte de a atinge baza de date
    if not sku.strip() or not name.strip():
        raise ValueError("Codul SKU și numele produsului sunt obligatorii.")
    if unit_price < 0 or initial_stock < 0 or min_threshold < 0:
        raise ValueError("Prețul, stocul și pragul minim nu pot fi negative.")

    conn = get_connection(db_name)
    try:
        with conn:
            with conn.cursor() as cur:
                # Folosim %s ca placeholder pentru a preveni atacurile de tip SQL Injection.
                # RETURNING id este o facilitate PostgreSQL care ne returnează ID-ul nou creat.
                cur.execute(
                    """
                    INSERT INTO products (sku, name, unit_price, current_stock, min_threshold)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (sku.strip().upper(), name.strip(), unit_price, initial_stock, min_threshold),
                )
                product_id = cur.fetchone()["id"]

                # Dacă produsul pornește cu stoc > 0, păstrăm trasabilitatea în jurnalul de mișcări
                if initial_stock > 0:
                    cur.execute(
                        """
                        INSERT INTO stock_movements (product_id, movement_type, quantity, note)
                        VALUES (%s, 'IN', %s, 'Stoc inițial la adăugare produs');
                        """,
                        (product_id, initial_stock),
                    )
                return product_id
    except psycopg2.errors.UniqueViolation:
        # Prindem eroarea specifică PostgreSQL când cineva încearcă să bage un SKU duplicat
        raise ValueError(f"Există deja un produs cu codul SKU '{sku.strip().upper()}'.")
    finally:
        conn.close()


def update_product(
    product_id: int,
    name: str,
    unit_price: float,
    min_threshold: int,
    db_name: str = None,
) -> None:
    """Actualizează numele, prețul și pragul de alertă al unui produs existent."""
    if not name.strip():
        raise ValueError("Numele produsului este obligatoriu.")
    if unit_price < 0 or min_threshold < 0:
        raise ValueError("Prețul și pragul minim nu pot fi negative.")

    conn = get_connection(db_name)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE products
                    SET name = %s, unit_price = %s, min_threshold = %s
                    WHERE id = %s;
                    """,
                    (name.strip(), unit_price, min_threshold, product_id),
                )
    finally:
        conn.close()


def register_movement(
    product_id: int,
    movement_type: str,
    quantity: int,
    note: str = "",
    db_name: str = None,
) -> None:
    """
    Execută o intrare (IN) sau o ieșire (OUT) de stoc în mod atomic.
    """
    if movement_type not in ("IN", "OUT"):
        raise ValueError("Tipul mișcării trebuie să fie 'IN' sau 'OUT'.")
    if quantity <= 0:
        raise ValueError("Cantitatea trebuie să fie mai mare decât 0.")

    conn = get_connection(db_name)
    try:
        with conn:
            with conn.cursor() as cur:
                # FOR UPDATE blochează acest rând în PostgreSQL până se termină tranzacția.
                # Dacă 2 utilizatori vând același produs simultan, al doilea așteaptă să termine primul,
                # prevenind astfel vânzarea aceluiași produs de două ori (race condition).
                cur.execute(
                    "SELECT current_stock, name FROM products WHERE id = %s FOR UPDATE;",
                    (product_id,),
                )
                row = cur.fetchone()

                if not row:
                    raise ValueError("Produsul selectat nu există.")

                current_stock = row["current_stock"]

                # Regulă critică ERP: nu permitem stoc negativ la ieșiri
                if movement_type == "OUT" and quantity > current_stock:
                    raise ValueError(
                        f"Stoc insuficient pentru '{row['name']}'. Disponibil: {current_stock}, Cerut: {quantity}."
                    )

                new_stock = current_stock + quantity if movement_type == "IN" else current_stock - quantity

                # Actualizăm stocul și scriem în istoric în aceeași tranzacție
                cur.execute(
                    "UPDATE products SET current_stock = %s WHERE id = %s;",
                    (new_stock, product_id),
                )
                cur.execute(
                    """
                    INSERT INTO stock_movements (product_id, movement_type, quantity, note)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (product_id, movement_type, quantity, note.strip()),
                )
    finally:
        conn.close()


def get_all_products(db_name: str = None) -> List[Dict]:
    """Returnează toate produsele ordonate alfabetic."""
    conn = get_connection(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products ORDER BY name ASC;")
            rows = cur.fetchall()
            # Convertim tipul Decimal din PostgreSQL în float Python pentru afișare ușoară în Pandas/Streamlit
            for r in rows:
                r["unit_price"] = float(r["unit_price"])
            return [dict(r) for r in rows]
    finally:
        conn.close()


def get_low_stock_products(db_name: str = None) -> List[Dict]:
    """Returnează doar produsele unde stocul curent a ajuns sub sau la pragul minim."""
    conn = get_connection(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM products WHERE current_stock <= min_threshold ORDER BY current_stock ASC;"
            )
            rows = cur.fetchall()
            for r in rows:
                r["unit_price"] = float(r["unit_price"])
            return [dict(r) for r in rows]
    finally:
        conn.close()


def get_movements_history(limit: int = 50, db_name: str = None) -> List[Dict]:
    """
    Face un JOIN între stock_movements și products pentru a afișa numele și SKU-ul
    produsului în loc de un simplu ID numeric.
    """
    conn = get_connection(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    m.id,
                    m.created_at AS data,
                    p.sku,
                    p.name AS produs,
                    m.movement_type AS tip,
                    m.quantity AS cantitate,
                    m.note AS observatii
                FROM stock_movements m
                JOIN products p ON m.product_id = p.id
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT %s;
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def seed_demo_data(db_name: str = None) -> None:
    """Inserează 5 produse de test (ignorându-le pe cele care există deja)."""
    demo_products = [
        ("LAP-001", "Laptop Dell Latitude 5540", 4200.00, 8, 3),
        ("MON-024", "Monitor Dell 24 inch IPS", 850.00, 2, 5),      # Sub prag (2 <= 5) -> va declanșa alertă
        ("KBD-101", "Tastatură Mecanică Logitech", 350.00, 15, 4),
        ("MOU-202", "Mouse Wireless MX Master", 420.00, 3, 5),       # Sub prag (3 <= 5) -> va declanșa alertă
        ("DOC-303", "Docking Station USB-C", 680.00, 0, 2),          # Stoc 0 -> va declanșa alertă
    ]
    for sku, name, price, stock, threshold in demo_products:
        try:
            add_product(sku, name, price, stock, threshold, db_name=db_name)
        except ValueError:
            pass  # Dacă produsul există deja, trecem mai departe fără eroare