"use client";

import Link from "next/link";
import { useState } from "react";
import { StockListItem } from "@/components/StockListItem";
import copy from "@/content/copy.ko.json";
import { useQuotes } from "@/lib/useQuotes";
import { useWatchlist } from "@/lib/useWatchlist";
import {
  MAX_GROUPS,
  MAX_NAME_LENGTH,
  createGroup,
  deleteGroup,
  mergedItems,
  moveToGroup,
  moveWithinGroup,
  removeFromGroup,
  renameGroup,
} from "@/lib/watchlist";

/**
 * 관심종목 화면(`/watchlist`, DEC-055): 증권사 앱 관심종목 구성(그룹 탭 · 편집 · 종목 행에 종가·전일대비·미니 캔들).
 * 데이터는 이 브라우저 localStorage에만 있다. "통합" 탭은 모든 그룹을 합친 읽기 전용 보기이고, 순서·그룹 이동·이름 변경은
 * 각 그룹 탭에서 한다.
 */
const ALL = "all";

export function WatchlistClient() {
  const { state, update } = useWatchlist();
  const [activeId, setActiveId] = useState<string>(ALL);
  const [editing, setEditing] = useState(false);
  const [newName, setNewName] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const group = state.groups.find((g) => g.id === activeId) ?? null;
  const activeKey = group ? group.id : ALL; // 삭제 등으로 사라진 그룹이면 통합으로 돌아간다
  const items = group ? group.items : mergedItems(state);
  const quotes = useQuotes(items.map((i) => i.code));

  const selectTab = (id: string) => {
    setActiveId(id);
    setConfirmDelete(false);
    setRenameValue("");
  };

  return (
    <section className="watchlist-page">
      <div className="watchlist-page__head">
        <h1>{copy.watchlist.pageTitle}</h1>
        <button
          type="button"
          className="watchlist-page__edit"
          aria-pressed={editing}
          onClick={() => {
            setEditing((v) => !v);
            setConfirmDelete(false);
          }}
        >
          {editing ? copy.watchlist.done : copy.watchlist.edit}
        </button>
      </div>

      <div role="tablist" aria-label={copy.watchlist.tabsLabel} className="watchlist-tabs">
        <button
          type="button"
          role="tab"
          id="wl-tab-all"
          aria-selected={activeKey === ALL}
          className="watchlist-tabs__tab"
          onClick={() => selectTab(ALL)}
        >
          {copy.watchlist.tabAll}
        </button>
        {state.groups.map((g) => (
          <button
            key={g.id}
            type="button"
            role="tab"
            id={`wl-tab-${g.id}`}
            aria-selected={activeKey === g.id}
            className="watchlist-tabs__tab"
            onClick={() => selectTab(g.id)}
          >
            {g.name}
          </button>
        ))}
      </div>

      {editing && (
        <div className="watchlist-edit">
          {group ? (
            <div className="watchlist-edit__row">
              <label htmlFor="wl-rename">{copy.watchlist.groupNameLabel}</label>
              <input
                id="wl-rename"
                type="text"
                maxLength={MAX_NAME_LENGTH}
                value={renameValue === "" ? group.name : renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
              />
              <button
                type="button"
                onClick={() => {
                  update((s) => renameGroup(s, group.id, renameValue === "" ? group.name : renameValue));
                  setRenameValue("");
                }}
              >
                {copy.watchlist.groupRename}
              </button>
              <button
                type="button"
                className={confirmDelete ? "watchlist-edit__danger" : ""}
                disabled={state.groups.length <= 1}
                onClick={() => {
                  if (!confirmDelete) {
                    setConfirmDelete(true);
                    return;
                  }
                  update((s) => deleteGroup(s, group.id));
                  setConfirmDelete(false);
                  setActiveId(ALL);
                }}
              >
                {confirmDelete ? copy.watchlist.groupDeleteConfirm : copy.watchlist.groupDelete}
              </button>
            </div>
          ) : (
            <p className="stock-tabs__note">{copy.watchlist.editNotAllInfo}</p>
          )}
          <form
            className="watchlist-edit__row"
            onSubmit={(e) => {
              e.preventDefault();
              update((s) => createGroup(s, newName));
              setNewName("");
            }}
          >
            <label htmlFor="wl-new">{copy.watchlist.groupAddLabel}</label>
            <input
              id="wl-new"
              type="text"
              maxLength={MAX_NAME_LENGTH}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <button type="submit" disabled={state.groups.length >= MAX_GROUPS}>
              {copy.watchlist.groupAdd}
            </button>
          </form>
          {state.groups.length >= MAX_GROUPS && (
            <p className="stock-tabs__note">{copy.watchlist.groupLimit.replace("{max}", String(MAX_GROUPS))}</p>
          )}
          <p className="stock-tabs__note">{copy.watchlist.groupDeleteHint}</p>
        </div>
      )}

      <div role="tabpanel" aria-labelledby={`wl-tab-${activeKey}`}>
        {items.length === 0 ? (
          <div className="watchlist-empty">
            <h2>{copy.watchlist.emptyTitle}</h2>
            <p>{copy.watchlist.emptyBody}</p>
            <Link href="/stocks" className="watchlist-empty__cta">
              {copy.watchlist.emptyCta}
            </Link>
          </div>
        ) : (
          <ul className="stock-list">
            {items.map((it, idx) => (
              <StockListItem
                key={it.code}
                item={{ stock_code: it.code, name: it.name, market: it.market }}
                quote={quotes[it.code]}
                star={!editing}
              >
                {editing && (
                  <span className="watchlist-row-actions">
                    {group && (
                      <>
                        <button
                          type="button"
                          aria-label={`${it.name} ${copy.watchlist.moveUp}`}
                          disabled={idx === 0}
                          onClick={() => update((s) => moveWithinGroup(s, group.id, it.code, -1))}
                        >
                          ▲
                        </button>
                        <button
                          type="button"
                          aria-label={`${it.name} ${copy.watchlist.moveDown}`}
                          disabled={idx === items.length - 1}
                          onClick={() => update((s) => moveWithinGroup(s, group.id, it.code, 1))}
                        >
                          ▼
                        </button>
                        {state.groups.length > 1 && (
                          <select
                            aria-label={`${it.name} ${copy.watchlist.moveToGroup}`}
                            value=""
                            onChange={(e) => {
                              const to = e.target.value;
                              if (to) update((s) => moveToGroup(s, group.id, to, it.code));
                            }}
                          >
                            <option value="">{copy.watchlist.moveSelectPlaceholder}</option>
                            {state.groups
                              .filter((g) => g.id !== group.id)
                              .map((g) => (
                                <option key={g.id} value={g.id}>
                                  {g.name}
                                </option>
                              ))}
                          </select>
                        )}
                        <button
                          type="button"
                          aria-label={`${it.name} ${copy.watchlist.remove}`}
                          onClick={() => update((s) => removeFromGroup(s, group.id, it.code))}
                        >
                          {copy.watchlist.remove}
                        </button>
                      </>
                    )}
                  </span>
                )}
              </StockListItem>
            ))}
          </ul>
        )}
      </div>

      <p className="stock-tabs__note">{copy.watchlist.storageNotice}</p>
    </section>
  );
}
