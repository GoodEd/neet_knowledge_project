import streamlit as st

def hide_admin_and_toolbar():
    hide_streamlit_style = """
    <style>
        [data-testid="stSidebarNavItems"] li:nth-child(4) {
            display: none;
        }
        
        header[data-testid="stHeader"] {
            display: none !important;
        }
        
        .block-container {
            padding-top: 2rem !important;
        }
    </style>
    """
    st.markdown(hide_streamlit_style, unsafe_allow_html=True)
