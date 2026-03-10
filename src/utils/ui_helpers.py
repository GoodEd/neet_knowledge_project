import streamlit as st
import streamlit.components.v1 as components


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

        /* Taller chat input box */
        [data-testid="stChatInputTextArea"] {
            min-height: 80px !important;
        }

        /* Align attach icon to bottom-left */
        [data-testid="stChatInput"] [data-testid="stChatInputFileUploadButton"] {
            align-self: flex-end !important;
        }
    </style>
    """
    st.markdown(style_block, unsafe_allow_html=True)


_GTM_JS = """
(function() {
  var pw = window.parent || window;
  var pd = pw.document;
  if (pw.__nk_gtm_loaded) return;
  pw.__nk_gtm_loaded = true;
  pw.dataLayer = pw.dataLayer || [];
  pw.dataLayer.push({'gtm.start': new Date().getTime(), event: 'gtm.js'});
  var s = pd.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtm.js?id=GTM-N5B8N77';
  pd.head.appendChild(s);
})();
"""


def setup_public_page_chrome():
    apply_toolbar_style()
    components.html(f"<script>{_GTM_JS}</script>", height=0)
