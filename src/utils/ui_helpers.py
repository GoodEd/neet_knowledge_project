import streamlit as st


def apply_toolbar_style():
    style_block = """
    <style>
        header[data-testid="stHeader"] {
            display: none !important;
        }

        .block-container {
            padding-top: 2rem !important;
        }

        section[data-testid="stSidebar"] {
            display: none !important;
        }

        button[data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
    </style>
    """
    st.markdown(style_block, unsafe_allow_html=True)


def setup_public_page_chrome():
    apply_toolbar_style()
