/*
 * Streamlit 기본 위젯으로는 할 수 없는 동작을 보완한다 (PRD 3.3, 6장).
 * - 이름 더블클릭 → 수정, 편집 중 Esc → 취소
 * - 편집 시작 시 편집창 자동 포커스
 * - 추가/삭제/저장/취소/완료 항목 삭제 뒤 키보드 포커스 이동
 * - 수정/삭제 버튼에 아이템 이름이 들어간 aria-label, 개수 변경을 화면 낭독기에 알림
 *
 * Streamlit은 조작할 때마다 서버에서 다시 실행되어 화면을 갱신하므로,
 * 클릭 시점에 "다시 그린 뒤 어디로 포커스를 옮길지(pending)"를 기억해 두고
 * 화면 변경이 SETTLE_MS 동안 멈추면 적용한다.
 * (stApp의 data-test-script-state는 form 제출 같은 빠른 재실행에서 바뀌지 않을 때가 있어 기준으로 쓰지 않는다)
 */
(() => {
  if (window.__shoppingEnhancer) return;
  window.__shoppingEnhancer = true;

  const ADD_LABEL = '추가할 아이템 이름';
  const SETTLE_MS = 200;
  let pending = null;       // { kind: 'add' } | { kind: 'row', index, prefer: 'edit' | 'delete' }
  let settleTimer = null;
  let editingSeen = null;   // 자동 포커스를 이미 한 편집창 (같은 편집 중 다시 포커스를 뺏지 않기 위함)
  let lastCount = null;

  const isRunning = () =>
    document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state') === 'running';
  const rows = () => [...document.querySelectorAll('[class*="st-key-check_"]')]
    .map((el) => el.closest('[data-testid="stHorizontalBlock"]'));
  // 편집 form 안에도 (저장/취소용) 가로 블록이 있으므로, closest() 대신 아이템 행 목록에서 찾는다
  const rowOf = (el) => rows().find((row) => row.contains(el));
  const rowName = (row) => (row?.querySelector('input[type=checkbox]')?.getAttribute('aria-label') ?? '')
    .replace(/ 구매 완료$/, '');
  const rowButton = (row, kind) => row?.querySelector(`[class*="st-key-${kind}_"] button`);
  const addInput = () => document.querySelector(`input[aria-label="${ADD_LABEL}"]`);
  const editInput = () => document.querySelector('input[aria-label$=" 이름 수정"]');
  const buttonText = (btn) => btn.textContent.trim();

  // 화면 낭독기용 알림 영역 (Streamlit이 다시 그려도 사라지지 않도록 body에 직접 둔다)
  const live = document.createElement('div');
  live.className = 'sr-only';
  live.setAttribute('aria-live', 'polite');
  document.body.append(live);

  function labelButtons() {
    for (const row of rows()) {
      const name = rowName(row);
      rowButton(row, 'edit')?.setAttribute('aria-label', `${name} 수정`);
      rowButton(row, 'delete')?.setAttribute('aria-label', `${name} 삭제`);
    }
  }

  function announceCount() {
    const text = document.querySelector('.item-count')?.textContent.trim();
    if (text && text !== lastCount) {
      if (lastCount !== null) live.textContent = text;
      lastCount = text;
    }
  }

  function autofocusEdit() {
    const input = editInput();
    const key = input?.getAttribute('aria-label') ?? null;
    if (input && key !== editingSeen && !pending) {
      input.focus();
      // Streamlit이 입력창을 만든 직후 값을 채우면서 선택이 풀리므로, 값이 채워진 뒤 한 번 더 전체 선택한다
      setTimeout(() => { if (document.activeElement === input) input.select(); }, 120);
    }
    editingSeen = key;
  }

  // 클릭 뒤 화면이 한 번 이상 바뀌고 그 변경이 멈추면 pending 포커스를 적용한다.
  // 서버 응답이 느려 아무 변화가 없으면 MAX_WAIT_MS 뒤에 적용한다.
  const MAX_WAIT_MS = 1500;

  function schedulePending() {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => {
      if (!pending) return;
      const waited = Date.now() - pending.at;
      if ((pending.changed && !isRunning()) || waited >= MAX_WAIT_MS) applyPending();
      else schedulePending();
    }, SETTLE_MS);
  }

  function setPending(next) {
    pending = { ...next, at: Date.now(), changed: false };
    schedulePending();
  }

  function applyPending() {
    const p = pending;
    pending = null;
    if (p.kind === 'add') {
      addInput()?.focus();
      return;
    }
    const all = rows();
    const row = all[p.index] ?? all[p.index - 1];
    const target = rowButton(row, p.prefer) ?? row?.querySelector('input[type=checkbox]') ?? addInput();
    target?.focus();
  }

  function update() {
    labelButtons();
    announceCount();
    if (pending) {
      pending.changed = true;
      schedulePending();
    } else {
      autofocusEdit();
    }
  }

  // 클릭 직후 "재실행 뒤 포커스 위치"를 기억한다
  document.addEventListener('click', (event) => {
    const btn = event.target.closest('button');
    if (!btn) return;
    const index = rows().indexOf(rowOf(btn));
    const text = buttonText(btn);

    if (btn.closest('[class*="st-key-delete_"]')) setPending({ kind: 'row', index, prefer: 'delete' });
    else if ((text === '저장' || text === '취소') && index !== -1) setPending({ kind: 'row', index, prefer: 'edit' });
    else if (text === '추가' || text === '완료 항목 삭제') setPending({ kind: 'add' });
  }, true);

  document.addEventListener('keydown', (event) => {
    const input = event.target;
    if (event.isComposing || !input.matches?.('input[aria-label$=" 이름 수정"]')) return;
    if (event.key === 'Enter') {
      setPending({ kind: 'row', index: rows().indexOf(rowOf(input)), prefer: 'edit' });
    } else if (event.key === 'Escape') {
      event.preventDefault();
      const cancel = [...(input.closest('[data-testid="stForm"]')?.querySelectorAll('button') ?? [])]
        .find((b) => buttonText(b) === '취소');
      cancel?.click();
    }
  }, true);

  document.addEventListener('dblclick', (event) => {
    const name = event.target.closest('.item-name');
    if (name) rowButton(rowOf(name), 'edit')?.click();
  });

  new MutationObserver(update).observe(document.body, { subtree: true, childList: true, characterData: true });
  update();
})();
