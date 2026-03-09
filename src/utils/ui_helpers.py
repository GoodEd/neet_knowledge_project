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


GTM_HTML = """
<script>
window.dataLayer = window.dataLayer || [];
(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','GTM-N5B8N77');
</script>
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-N5B8N77"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
"""


def setup_public_page_chrome():
    apply_toolbar_style()
    st.markdown(GTM_HTML, unsafe_allow_html=True)
