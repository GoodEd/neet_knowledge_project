import streamlit as st
import redis
import json
import os

st.set_page_config(page_title="Chat History", layout="wide")

st.title("📜 Your Chat History")

def get_redis_client():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        return redis.from_url(redis_url)
    except Exception as e:
        return None

r = get_redis_client()

if not r:
    st.error("Cannot connect to history database. Please try again later.")
    st.stop()

# Basic approach: Ask user to paste their Session ID to restore
st.markdown("""
To restore a previous chat, paste your **Session ID** below. 
You can find this ID at the top of your previous chat screen.
""")

col1, col2 = st.columns([3, 1])

with col1:
    lookup_id = st.text_input("Session ID")

with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    search_pressed = st.button("Load History", use_container_width=True)

if search_pressed and lookup_id:
    redis_key = f"chat_history:{lookup_id}"
    
    if r.exists(redis_key):
        st.success(f"History found! Click the button below to resume your chat.")
        st.link_button(f"Resume Chat Session", f"/Chat?session_id={lookup_id}", type="primary")
        
        with st.expander("Preview Conversation"):
            messages = json.loads(r.get(redis_key))
            for msg in messages:
                role = "👤 You" if msg["role"] == "user" else "🤖 Assistant"
                st.markdown(f"**{role}:** {msg['content'][:100]}...")
    else:
        st.warning("No history found for that Session ID. It may have expired.")

st.divider()
st.caption("Chat histories are securely stored for 7 days.")
