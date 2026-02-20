# Streamlit Multi-Role Architecture Plan

## Current State
`app.py` has a sidebar for "Manage Sources" and a main panel for "Chat". This mixes concerns. A student shouldn't see or be able to trigger "Ingest All Sources".

## Proposed Architecture: Multi-Page App with Auth/Roles

Streamlit supports multipage apps natively by creating a `pages/` directory.

### 1. Directory Structure
```
neet_knowledge_project/
├── Home.py                  # Entry point (Student Chat by default)
├── pages/
│   ├── 1_Chat.py           # Student interface
│   ├── 2_History.py        # Student history (requires DB/Redis)
│   └── 3_Admin.py          # Content Manager interface (Password protected)
```

### 2. User Roles & Access Control
- **Students**: Default role. Can access Chat and History.
- **Admin**: Must enter a password/token to access the Admin page.

#### Simple Admin Auth (Streamlit Native)
We can use Streamlit's session state and a simple password field in the Admin page to unlock content management features.

```python
# pages/3_Admin.py
import streamlit as st

def check_password():
    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False

    if not st.session_state.admin_authenticated:
        password = st.text_input("Admin Password", type="password")
        if password == os.getenv("ADMIN_PASSWORD", "default_secret"):
            st.session_state.admin_authenticated = True
            st.rerun()
        return False
    return True

if check_password():
    # Render Content Manager UI
```

### 3. Session & Chat History (For Students)
Currently, `st.session_state.messages` only persists while the browser tab is open. If a student refreshes, the history is gone.

**Solution: Redis or SQLite**
Since we already planned/deployed Redis in the AWS ECS setup, we should use it for session history.

*   Generate a unique `session_id` cookie for the student (or use `st.query_params`).
*   Store chat messages in Redis under `user:session_id`.
*   The History page reads all sessions for that user (if we implement a basic user ID system).

### 4. Implementation Steps

1.  **Refactor `app.py`** -> Rename to `Home.py` or move to `pages/1_Chat.py`.
2.  **Extract Admin UI**: Move the sidebar source management code into a dedicated `pages/3_Admin.py` with password protection.
3.  **Implement Redis History**:
    *   Add a utility class `ChatHistoryManager(redis_client)`.
    *   Load history on app start based on a generated session cookie.
    *   Append to Redis on every message.

### 5. Route Mapping (Current)
- `app.py` -> `/` (Home)
- `pages/1_Chat.py` -> `/Chat`
- `pages/2_History.py` -> `/History`
- `pages/3_Admin.py` -> `/Admin`

This approach requires minimal external dependencies and works natively within Streamlit and the existing AWS architecture.
