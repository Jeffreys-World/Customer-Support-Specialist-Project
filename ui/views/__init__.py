"""One module per navigation destination.

Named ``views`` rather than ``pages`` on purpose: a top-level ``pages/``
directory next to the entry script triggers Streamlit's legacy multipage
auto-discovery, which would fight the explicit ``st.navigation`` tree in
``app.py``.
"""
