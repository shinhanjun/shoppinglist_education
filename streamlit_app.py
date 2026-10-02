"""쇼핑 리스트 앱 (Streamlit 버전)

PRD.md의 기능 요구사항을 Streamlit으로 구현한다.
- 데이터 저장: 브라우저 localStorage 대신 같은 폴더의 shopping_list.json 파일 (PRD 3.6)
- 실행: streamlit run streamlit_app.py
"""

import html
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "shopping_list.json"


# ===== 데이터 저장 (PRD 3.6, 4장) =====
# 세션(탭·기기)마다 목록 복사본을 들고 있으면 저장할 때 서로의 변경을 덮어쓴다.
# 그래서 화면을 그릴 때와 변경할 때 모두 파일을 새로 읽고, 변경은 잠금 안에서 "읽기 → 수정 → 쓰기"로 처리한다.
@st.cache_resource
def _file_lock() -> threading.Lock:
    """모든 세션이 공유하는 파일 잠금."""
    return threading.Lock()


def now_ms() -> int:
    return int(time.time() * 1000)


def _load_unlocked() -> tuple[list[dict], bool]:
    """파일을 읽어 PRD 4장 모델 형태로 정규화한다. (목록, 정규화로 내용이 바뀌었는지)"""
    try:
        parsed = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], False
    if not isinstance(parsed, list):
        return [], False

    items, seen_ids, changed = [], set(), False
    for item in parsed:
        if not (isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("name"), str)):
            changed = True
            continue
        item_id = item["id"]
        if item_id in seen_ids:  # 같은 id가 또 나오면 새 id를 붙인다 (위젯 key 충돌 방지)
            item_id, changed = str(uuid.uuid4()), True
        seen_ids.add(item_id)
        items.append({
            "id": item_id,
            "name": item["name"],
            "checked": item.get("checked") is True,
            "createdAt": item["createdAt"] if isinstance(item.get("createdAt"), (int, float)) else now_ms(),
        })
    return items, changed


def _save_unlocked(items: list[dict]) -> None:
    """임시 파일에 쓴 뒤 교체해서, 쓰는 도중에 읽어도 깨진 파일을 보지 않게 한다."""
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DATA_FILE)


def read_items() -> list[dict]:
    with _file_lock():
        items, changed = _load_unlocked()
        if changed:
            _save_unlocked(items)
        return items


def modify_items(change: Callable[[list[dict]], list[dict] | None]) -> None:
    """최신 파일 내용에 change를 적용해 저장한다. change는 목록을 직접 고치거나 새 목록을 반환한다."""
    try:
        with _file_lock():
            items, _ = _load_unlocked()
            result = change(items)
            _save_unlocked(items if result is None else result)
    except OSError:
        st.toast("저장하지 못했어요. 파일 권한을 확인해 주세요.", icon="⚠️")


def find(items: list[dict], item_id: str) -> dict | None:
    return next((it for it in items if it["id"] == item_id), None)


# ===== 동작 (콜백) =====
def add_item() -> None:
    """PRD 3.1: 앞뒤 공백 제거, 빈 값은 추가하지 않음, 추가 후 입력창 비움."""
    name = st.session_state.new_item.strip()
    if not name:
        return
    modify_items(lambda items: items.append(
        {"id": str(uuid.uuid4()), "name": name, "checked": False, "createdAt": now_ms()}
    ))
    st.session_state.new_item = ""


def toggle_item(item_id: str) -> None:
    """PRD 3.5: 화면의 체크 상태를 그대로 저장한다 (뒤집기가 아니라 값 지정이라 다른 세션과 충돌해도 안전)."""
    checked = st.session_state[f"check_{item_id}"]

    def change(items):
        item = find(items, item_id)
        if item:
            item["checked"] = checked

    modify_items(change)


def start_edit(item_id: str, name: str) -> None:
    """PRD 3.3: 한 번에 하나만 편집."""
    st.session_state.editing_id = item_id
    st.session_state.edit_value = name


def save_edit(item_id: str) -> None:
    """PRD 3.3: 빈 값이면 기존 값 유지."""
    new_name = st.session_state.edit_value.strip()
    if new_name:
        def change(items):
            item = find(items, item_id)
            if item:
                item["name"] = new_name

        modify_items(change)
    st.session_state.editing_id = None


def cancel_edit() -> None:
    st.session_state.editing_id = None


def delete_item(item_id: str) -> None:
    """PRD 3.4"""
    modify_items(lambda items: [it for it in items if it["id"] != item_id])
    if st.session_state.editing_id == item_id:
        st.session_state.editing_id = None


def clear_checked() -> None:
    """PRD 3.4: 체크된 아이템 일괄 삭제."""
    modify_items(lambda items: [it for it in items if not it["checked"]])


# ===== 화면 =====
st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")

# 스타일과, Streamlit 기본 위젯으로 안 되는 동작(더블클릭·Esc·포커스·aria) 보완 스크립트
st.html(f"<style>{(BASE_DIR / 'streamlit_style.css').read_text(encoding='utf-8')}</style>")
st.html(
    f"<script>{(BASE_DIR / 'streamlit_enhance.js').read_text(encoding='utf-8')}</script>",
    unsafe_allow_javascript=True,
)

st.session_state.setdefault("editing_id", None)
items = read_items()

# 다른 세션에서 편집 중인 항목을 지웠으면 편집 상태를 정리한다
if st.session_state.editing_id and not find(items, st.session_state.editing_id):
    st.session_state.editing_id = None

st.title("🛒 쇼핑 리스트")

# 입력 영역: form이라 Enter로도 추가된다 (PRD 3.1)
with st.form("add_form", clear_on_submit=False, border=False):
    col_input, col_button = st.columns([5, 1])
    col_input.text_input(
        "추가할 아이템 이름",
        key="new_item",
        placeholder="아이템을 입력하세요...",
        label_visibility="collapsed",
    )
    col_button.form_submit_button("추가", on_click=add_item, type="primary", width="stretch")

st.divider()

# 목록 (PRD 3.2)
if not items:
    st.markdown('<p class="empty-message">쇼핑 리스트가 비어 있어요</p>', unsafe_allow_html=True)

for item in items:
    item_id = item["id"]
    editing = item_id == st.session_state.editing_id
    if editing:
        col_check, col_name = st.columns([0.6, 8.4], vertical_alignment="center")
    else:
        col_check, col_name, col_edit, col_delete = st.columns([0.6, 6, 1.2, 1.2], vertical_alignment="center")

    # 다른 세션의 변경도 반영되도록 파일의 체크 상태를 위젯 상태에 맞춰 둔다
    st.session_state[f"check_{item_id}"] = item["checked"]
    col_check.checkbox(
        f"{item['name']} 구매 완료",
        key=f"check_{item_id}",
        on_change=toggle_item,
        args=(item_id,),
        label_visibility="collapsed",
    )

    if editing:
        # 인라인 편집 모드: form이라 Enter로 저장 (PRD 3.3)
        with col_name.form(f"edit_form_{item_id}", border=False):
            st.text_input(f"{item['name']} 이름 수정", key="edit_value", label_visibility="collapsed")
            save_col, cancel_col = st.columns(2)
            save_col.form_submit_button("저장", on_click=save_edit, args=(item_id,), type="primary", width="stretch")
            cancel_col.form_submit_button("취소", on_click=cancel_edit, width="stretch")
    else:
        css_class = "item-name checked" if item["checked"] else "item-name"
        # 이름을 HTML 이스케이프 후 넣어 XSS 방지 (웹 버전의 textContent와 같은 역할)
        col_name.markdown(f'<div class="{css_class}">{html.escape(item["name"])}</div>', unsafe_allow_html=True)
        col_edit.button("수정", key=f"edit_{item_id}", on_click=start_edit, args=(item_id, item["name"]))
        col_delete.button("삭제", key=f"delete_{item_id}", on_click=delete_item, args=(item_id,))

st.divider()

# footer: 개수 + 완료 항목 삭제 (PRD 3.2, 3.4)
remaining = sum(1 for it in items if not it["checked"])
col_count, col_clear = st.columns([3, 2], vertical_alignment="center")
col_count.markdown(f'<p class="item-count">전체 {len(items)}개 · 남은 항목 {remaining}개</p>', unsafe_allow_html=True)
col_clear.button("완료 항목 삭제", on_click=clear_checked, disabled=remaining == len(items), width="stretch")
