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
    </style>
    """
    st.markdown(style_block, unsafe_allow_html=True)


def render_public_sidebar_links():
    with st.sidebar:
        st.page_link("pages/1_Chat.py", label="Chat", icon="💬")


def setup_public_page_chrome():
    apply_toolbar_style()
    render_public_sidebar_links()
