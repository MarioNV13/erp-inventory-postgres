# 📦 Mini-ERP: Gestiune Stocuri & Alerte (Inventory Tracker)

Aplicație web pentru gestionarea nomenclatorului de produse, urmărirea mișcărilor de stoc (intrări/ieșiri) și alertarea automată la atingerea pragului minim, construită cu **Python**, **PostgreSQL** și **Streamlit**.

## 🚀 Funcționalități
- **Gestiune Produse (CRUD):** Adăugare produse cu cod SKU unic, editare preț și prag minim de alertă, filtrare rapidă după nume/SKU.
- **Tranzacții Stoc (IN / OUT):** Înregistrare intrări de marfă și vânzări cu actualizare automată a stocului și jurnalizare în istoric.
- **Integritatea Datelor (PostgreSQL):**
  - Prevenirea stocului negativ atât la nivel de aplicație, cât și prin constrângeri SQL (`CHECK`).
  - Blocare la nivel de rând (`SELECT ... FOR UPDATE`) pentru a evita inconsistențele la operațiuni simultane.
  - Utilizarea tipului `NUMERIC(10, 2)` pentru precizie financiară.
- **Alerte & Raportare:** Indicatori KPI în timp real, evidențierea produselor sub pragul critic și export în format CSV.

