from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import streamlit as st


APP_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = APP_DIR.parent
SRC_DIR = ROOT_DIR / "src"
if str(APP_DIR) not in sys.path:
    sys.path.append(str(APP_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

import dashboard  # noqa: E402
from storage.sqlite_store import SQLiteStore  # noqa: E402


def main() -> None:
    st.set_page_config(page_title="Gain Entity Vault", layout="wide")
    top_cols = st.columns([4, 1])
    top_cols[0].title("User Vault / Autofill Profile")
    try:
        top_cols[1].page_link("dashboard.py", label="Back to Dashboard", use_container_width=True)
    except Exception:  # noqa: BLE001
        top_cols[1].markdown("[Back to Dashboard](/)")

    if not dashboard.DB_PATH.exists():
        st.info(f"No database found at {dashboard.DB_PATH}.")
        return

    store = SQLiteStore(dashboard.DB_PATH)
    store.init_db()
    store.normalize_required_inputs()
    store.normalize_execution_state()

    with sqlite3.connect(dashboard.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        st.session_state["show_vault"] = True
        st.session_state["user_profile_vault_open"] = True
        if "vault_focus" not in st.session_state:
            st.session_state["vault_focus"] = "Credentials / Submission Consent"
            st.session_state["vault_field_group_selector"] = "Credentials / Submission Consent"
        dashboard.show_user_profile_autofill_vault(conn)


if __name__ == "__main__":
    main()
