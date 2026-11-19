import pytest
from src import database as db

# Folosim o bază de date separată ca să nu ștergem datele reale când rulăm testele
TEST_DB = "erp_inventory_test"


# @pytest.fixture(autouse=True) rulează automat ÎNAINTE de fiecare funcție de test
@pytest.fixture(autouse=True)
def clean_test_db():
    db.init_db(TEST_DB)
    conn = db.get_connection(TEST_DB)
    with conn:
        with conn.cursor() as cur:
            # TRUNCATE golește complet tabelele și resetează ID-urile la 1 înainte de fiecare test
            cur.execute("TRUNCATE TABLE stock_movements, products RESTART IDENTITY CASCADE;")
    conn.close()
    yield


def test_add_product_and_initial_stock():
    """Verifică adăugarea unui produs, transformarea SKU în majuscule și crearea mișcării inițiale."""
    db.add_product("mon-24", "Monitor 24 inch", 750.0, 10, 3, db_name=TEST_DB)
    products = db.get_all_products(db_name=TEST_DB)

    assert len(products) == 1
    assert products[0]["sku"] == "MON-24"
    assert products[0]["current_stock"] == 10

    movements = db.get_movements_history(db_name=TEST_DB)
    assert len(movements) == 1
    assert movements[0]["tip"] == "IN"


def test_prevent_duplicate_sku():
    """Verifică faptul că nu putem adăuga două produse cu același cod SKU (indiferent de litere mari/mici)."""
    db.add_product("KB-01", "Tastatură Mecanică", 300.0, 5, 2, db_name=TEST_DB)

    # Ne așteptăm ca funcția să arunce ValueError; dacă nu aruncă, testul pică
    with pytest.raises(ValueError, match="Există deja un produs"):
        db.add_product("kb-01", "Altă Tastatură", 250.0, 3, 1, db_name=TEST_DB)


def test_prevent_negative_stock_on_out():
    """Verifică blocarea vânzării când cantitatea cerută depășește stocul disponibil."""
    pid = db.add_product("MS-01", "Mouse Wireless", 120.0, 4, 2, db_name=TEST_DB)

    with pytest.raises(ValueError, match="Stoc insuficient"):
        db.register_movement(pid, "OUT", 5, "Comandă prea mare", db_name=TEST_DB)

    # Verificăm că stocul a rămas intact (4 bucăți)
    products = db.get_all_products(db_name=TEST_DB)
    assert products[0]["current_stock"] == 4


def test_low_stock_alert():
    """Verifică declanșarea alertei atunci când stocul scade sub pragul minim."""
    pid = db.add_product("USB-64", "Stick USB 64GB", 45.0, 6, 3, db_name=TEST_DB)
    assert len(db.get_low_stock_products(db_name=TEST_DB)) == 0

    # Scădem 4 bucăți -> rămân 2 bucăți (sub pragul de 3) -> trebuie să apară în alerte
    db.register_movement(pid, "OUT", 4, "Vânzare", db_name=TEST_DB)
    low = db.get_low_stock_products(db_name=TEST_DB)
    assert len(low) == 1
    assert low[0]["current_stock"] == 2