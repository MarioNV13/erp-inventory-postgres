import streamlit as st
import pandas as pd
import database as db

# Configurăm titlul tab-ului din browser și layout-ul pe toată lățimea ecranului
st.set_page_config(page_title="Mini ERP - Gestiune Stocuri", page_icon="📦", layout="wide")

# Ne asigurăm că tabelele există în PostgreSQL la fiecare pornire a aplicației
db.init_db()

# --- BARA LATERALĂ (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Administrare")
    st.write("Populează baza de date cu 5 produse de test pentru demonstrație:")
    if st.button("📥 Încarcă Date Demo"):
        db.seed_demo_data()
        st.success("Datele demo au fost încărcate!")
        st.rerun()  # Reîncarcă pagina pentru a afișa noile date în tabele

st.title("📦 Mini-ERP: Gestiune Stocuri & Alerte")

# Citim datele actuale din PostgreSQL
products = db.get_all_products()
low_stock = db.get_low_stock_products()

# --- 1. INDICATORI CHEIE (KPI CARDS) ---
total_products = len(products)
# Calculăm valoarea totală a inventarului (cantitate * preț unitar pentru fiecare produs)
total_value = sum(p["current_stock"] * p["unit_price"] for p in products)
critical_count = len(low_stock)

# Împărțim ecranul în 3 coloane egale
col1, col2, col3 = st.columns(3)
col1.metric("Total Produse în Nomenclator", total_products)
col2.metric("Valoare Totală Stoc", f"{total_value:,.2f} RON")
col3.metric(
    "Alerte Stoc Critic",
    critical_count,
    delta=f"-{critical_count} sub prag" if critical_count else "OK",
    delta_color="inverse",  # Afișează cu roșu când numărul de alerte > 0
)

st.divider()

# --- 2. ZONA DE ALERTE STOC CRITIC ---
if low_stock:
    st.error(f"⚠️ Atenție! {len(low_stock)} produs(e) au ajuns sub pragul minim de stoc:")
    # Transformăm lista de dicționare într-un tabel Pandas pentru afișare curată
    df_low = pd.DataFrame(low_stock)[["sku", "name", "current_stock", "min_threshold", "unit_price"]]
    df_low.columns = ["SKU", "Produs", "Stoc Actual", "Prag Minim", "Preț Unitar (RON)"]
    st.dataframe(df_low, use_container_width=True, hide_index=True)
else:
    st.success("✅ Toate produsele au stoc suficient.")

st.divider()

# --- 3. FORMULARE DE ACȚIUNE (2 COLOANE) ---
left_col, right_col = st.columns(2)

with left_col:
    st.subheader("➕ Adaugă Produs Nou")
    # clear_on_submit=True golește câmpurile formularului după salvare
    with st.form("add_product_form", clear_on_submit=True):
        sku = st.text_input("Cod SKU (ex: LAP-001)")
        name = st.text_input("Nume Produs (ex: Laptop Dell Latitude)")
        unit_price = st.number_input("Preț Unitar (RON)", min_value=0.0, step=10.0, format="%.2f")
        initial_stock = st.number_input("Stoc Inițial", min_value=0, step=1)
        min_threshold = st.number_input("Prag Minim Alertă", min_value=0, value=5, step=1)
        submitted = st.form_submit_button("Salvează Produs")

        if submitted:
            try:
                db.add_product(sku, name, unit_price, initial_stock, min_threshold)
                st.success(f"Produsul '{name}' a fost adăugat!")
                st.rerun()
            except ValueError as e:
                # Afișăm în interfață mesajul de eroare venit din database.py (ex: SKU duplicat)
                st.error(str(e))

with right_col:
    st.subheader("🔄 Înregistrează Intrare / Ieșire Stoc")
    if not products:
        st.info("Adaugă mai întâi cel puțin un produs pentru a înregistra mișcări de stoc.")
    else:
        with st.form("movement_form", clear_on_submit=True):
            # Construim un dicționar { "Text afișat în dropdown": id_produs }
            product_options = {
                f"{p['sku']} - {p['name']} (Stoc: {p['current_stock']})": p["id"]
                for p in products
            }
            selected_label = st.selectbox("Selectează Produsul", list(product_options.keys()))
            movement_type = st.radio(
                "Tip Operațiune",
                ["IN", "OUT"],
                format_func=lambda x: "📥 Intrare marfă (IN)" if x == "IN" else "📤 Ieșire / Vânzare (OUT)",
                horizontal=True,
            )
            quantity = st.number_input("Cantitate", min_value=1, step=1)
            note = st.text_input("Observații (ex: Factură furnizor #12 / Comandă client #45)")
            move_submitted = st.form_submit_button("Execută Mișcarea")

            if move_submitted:
                try:
                    db.register_movement(product_options[selected_label], movement_type, quantity, note)
                    st.success("Mișcarea de stoc a fost înregistrată!")
                    st.rerun()
                except ValueError as e:
                    # Afișăm eroarea dacă utilizatorul încearcă să scoată mai mult decât există pe stoc
                    st.error(str(e))

st.divider()

# --- 4. TAB-URI PENTRU NOMENCLATOR, EDITARE ȘI ISTORIC ---
tab1, tab2, tab3 = st.tabs(["📋 Nomenclator Produse", "✏️ Editează Produs", "🕒 Istoric Mișcări Stoc"])

with tab1:
    if products:
        search_query = st.text_input("🔍 Caută după nume sau cod SKU:", placeholder="Ex: Dell sau LAP-001")
        df_prod = pd.DataFrame(products)

        # Filtrăm tabelul în memorie dacă utilizatorul a scris ceva în căsuța de căutare
        if search_query.strip():
            mask = (
                df_prod["name"].str.contains(search_query, case=False)
                | df_prod["sku"].str.contains(search_query, case=False)
            )
            df_prod = df_prod[mask]

        if not df_prod.empty:
            # Calculăm coloane suplimentare pentru raportare
            df_prod["valoare_stoc"] = df_prod["current_stock"] * df_prod["unit_price"]
            df_prod["status"] = df_prod.apply(
                lambda r: "🔴 Critic" if r["current_stock"] <= r["min_threshold"] else "🟢 OK",
                axis=1,
            )
            df_display = df_prod[["status", "sku", "name", "current_stock", "min_threshold", "unit_price", "valoare_stoc"]]
            df_display.columns = ["Status", "SKU", "Produs", "Stoc Actual", "Prag Minim", "Preț Unitar (RON)", "Valoare Totală (RON)"]
            st.dataframe(df_display, use_container_width=True, hide_index=True)

            # Generăm fișierul CSV pentru descărcare directă în browser
            csv = df_display.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Exportă Stocul în CSV", data=csv, file_name="raport_stocuri.csv", mime="text/csv")
        else:
            st.warning("Niciun produs nu corespunde căutării.")
    else:
        st.info("Nu există produse înregistrate.")

with tab2:
    if products:
        edit_options = {f"{p['sku']} - {p['name']}": p for p in products}
        selected_edit_label = st.selectbox("Alege produsul de modificat", list(edit_options.keys()))
        prod_to_edit = edit_options[selected_edit_label]

        with st.form("edit_product_form"):
            new_name = st.text_input("Nume Produs", value=prod_to_edit["name"])
            new_price = st.number_input("Preț Unitar (RON)", min_value=0.0, value=float(prod_to_edit["unit_price"]), step=10.0)
            new_threshold = st.number_input("Prag Minim Alertă", min_value=0, value=int(prod_to_edit["min_threshold"]), step=1)
            edit_submitted = st.form_submit_button("Salvează Modificările")

            if edit_submitted:
                try:
                    db.update_product(prod_to_edit["id"], new_name, new_price, new_threshold)
                    st.success("Produsul a fost actualizat!")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    else:
        st.info("Nu există produse de editat.")

with tab3:
    movements = db.get_movements_history()
    if movements:
        df_mov = pd.DataFrame(movements)
        st.dataframe(df_mov, use_container_width=True, hide_index=True)
    else:
        st.info("Nu există mișcări de stoc înregistrate.")