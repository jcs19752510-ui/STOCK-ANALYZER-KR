"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import copy from "@/content/copy.ko.json";
import type { AdminMember } from "@/lib/auth/apiClient";

/**
 * 관리자 회원 관리 화면(DEC-074): 가입 신청 승인·거절, 회원 추가, 이름 수정, 권한 변경(일반↔관리자), 사용 중지/재사용, 비밀번호 초기화, 모든 기기 로그아웃, 삭제.
 * 모든 작업은 같은 사이트의 `POST /admin/actions`로 보내며, **실제 권한 확인은 서버(API)가 매번 DB에서** 한다 — 이 화면의 버튼 표시는 안내일 뿐이다.
 * 위험한 작업은 확인창을 거치고, 본인 계정에는 잠금 위험이 있는 작업(사용 중지·삭제·강등) 버튼을 보여 주지 않는다(서버도 막는다).
 */
type Filter = "pending" | "all";
type Editor = { kind: "rename" | "reset"; username: string } | null;

const RESULT_TEXT: Record<string, string> = {
  created: copy.admin.doneCreated,
  approved: copy.admin.doneApproved,
  rejected: copy.admin.doneRejected,
  enabled: copy.admin.doneEnabled,
  disabled: copy.admin.doneDisabled,
  role_changed: copy.admin.doneRoleChanged,
  renamed: copy.admin.doneRenamed,
  password_reset: copy.admin.donePasswordReset,
  sessions_revoked: copy.admin.doneSessionsRevoked,
  deleted: copy.admin.doneDeleted,
};

const dateFmt = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });

function formatDate(iso: string | null): string {
  if (!iso) return copy.admin.never;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? copy.admin.never : dateFmt.format(d);
}

const STATUS_TEXT = { pending: copy.admin.statusPending, active: copy.admin.statusActive, disabled: copy.admin.statusDisabled } as const;

export function AdminMembers({ initial, self }: { initial: AdminMember[]; self: string }) {
  const router = useRouter();
  const pendingCount = initial.filter((m) => m.status === "pending").length;
  const [filter, setFilter] = useState<Filter>(pendingCount > 0 ? "pending" : "all");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [editor, setEditor] = useState<Editor>(null);
  const [editorValue, setEditorValue] = useState("");

  const rows = filter === "pending" ? initial.filter((m) => m.status === "pending") : initial;

  async function send(body: Record<string, unknown>): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch("/admin/actions", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(body) });
      const data = (await response.json().catch(() => null)) as { ok?: boolean; result?: string; message?: unknown; code?: string; reauth?: boolean } | null;
      if (response.ok && data?.ok) {
        if (data.reauth) {
          window.location.assign(new URL("/login", window.location.origin).toString());
          return true;
        }
        setNotice({ kind: "ok", text: RESULT_TEXT[data.result ?? ""] ?? copy.admin.doneApproved });
        router.refresh();
        return true;
      }
      if (response.status === 401) {
        window.location.assign(new URL("/login?reason=expired", window.location.origin).toString());
        return false;
      }
      const text =
        typeof data?.message === "string" && data.message
          ? data.message
          : response.status === 403
            ? copy.admin.errorForbidden
            : copy.admin.errorUnavailable;
      setNotice({ kind: "error", text });
    } catch {
      setNotice({ kind: "error", text: copy.admin.errorUnavailable });
    } finally {
      setBusy(false);
    }
    return false;
  }

  async function run(action: string, member: AdminMember, confirmText: string | null, extra: Record<string, unknown> = {}) {
    if (confirmText && !window.confirm(`${member.username} (${member.displayName})\n\n${confirmText}`)) return;
    await send({ action, username: member.username, ...extra });
  }

  async function onEditorSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor) return;
    const ok = await send(editor.kind === "rename" ? { action: "rename", username: editor.username, displayName: editorValue } : { action: "reset_password", username: editor.username, password: editorValue });
    if (ok) {
      setEditor(null);
      setEditorValue("");
    }
  }

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const ok = await send({
      action: "create",
      username: String(data.get("username") ?? "").trim(),
      displayName: String(data.get("displayName") ?? "").trim(),
      password: String(data.get("password") ?? ""),
      role: String(data.get("role") ?? "user"),
    });
    if (ok) form.reset();
  }

  return (
    <div className="admin-members">
      <div className="admin-members__tabs" role="group" aria-label={copy.admin.pageTitle}>
        <button type="button" className="admin-members__tab" aria-pressed={filter === "pending"} onClick={() => setFilter("pending")}>
          {copy.admin.tabPending} ({pendingCount})
        </button>
        <button type="button" className="admin-members__tab" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
          {copy.admin.tabAll} ({initial.length})
        </button>
      </div>

      <div aria-live="polite">
        {notice ? (
          <p className={notice.kind === "ok" ? "admin-members__notice" : "admin-members__notice admin-members__notice--error"} role={notice.kind === "ok" ? "status" : "alert"}>
            {notice.text}
          </p>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <p>{filter === "pending" ? copy.admin.emptyPending : copy.admin.empty}</p>
      ) : (
        <div className="members-page__table-wrap">
          <table className="members-table admin-table">
            <caption className="sr-only">{copy.admin.tableCaption}</caption>
            <thead>
              <tr>
                <th scope="col">{copy.admin.columnUsername}</th>
                <th scope="col">{copy.admin.columnName}</th>
                <th scope="col">{copy.admin.columnRole}</th>
                <th scope="col">{copy.admin.columnStatus}</th>
                <th scope="col">{copy.admin.columnLastLogin}</th>
                <th scope="col">{copy.admin.columnSessions}</th>
                <th scope="col">{copy.admin.columnActions}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => {
                const isSelf = m.username === self;
                return (
                  <tr key={m.username} data-username={m.username}>
                    <th scope="row">
                      {m.username}
                      {isSelf ? ` ${copy.admin.you}` : ""}
                    </th>
                    <td>{m.displayName}</td>
                    <td>{m.role === "admin" ? copy.admin.roleAdmin : copy.admin.roleUser}</td>
                    <td>
                      {STATUS_TEXT[m.status]}
                      {m.locked ? ` · ${copy.admin.locked}` : ""}
                    </td>
                    <td>{formatDate(m.lastLoginAt)}</td>
                    <td>{m.activeSessions}</td>
                    <td>
                      <div className="admin-actions">
                        {m.status === "pending" ? (
                          <>
                            <button type="button" disabled={busy} onClick={() => run("approve", m, copy.admin.confirmApprove)} aria-label={`${m.username} ${copy.admin.actionApprove}`}>{copy.admin.actionApprove}</button>
                            <button type="button" disabled={busy} onClick={() => run("reject", m, copy.admin.confirmReject)} aria-label={`${m.username} ${copy.admin.actionReject}`}>{copy.admin.actionReject}</button>
                          </>
                        ) : (
                          <>
                            {!isSelf ? (
                              <button type="button" disabled={busy} onClick={() => run("set_role", m, m.role === "admin" ? copy.admin.confirmToUser : copy.admin.confirmToAdmin, { role: m.role === "admin" ? "user" : "admin" })} aria-label={`${m.username} ${m.role === "admin" ? copy.admin.actionToUser : copy.admin.actionToAdmin}`}>
                                {m.role === "admin" ? copy.admin.actionToUser : copy.admin.actionToAdmin}
                              </button>
                            ) : null}
                            <button type="button" disabled={busy} onClick={() => { setEditor({ kind: "rename", username: m.username }); setEditorValue(m.displayName); }} aria-label={`${m.username} ${copy.admin.actionRename}`}>{copy.admin.actionRename}</button>
                            <button type="button" disabled={busy} onClick={() => { setEditor({ kind: "reset", username: m.username }); setEditorValue(""); }} aria-label={`${m.username} ${copy.admin.actionReset}`}>{copy.admin.actionReset}</button>
                            <button type="button" disabled={busy} onClick={() => run("revoke_sessions", m, copy.admin.confirmRevoke)} aria-label={`${m.username} ${copy.admin.actionRevoke}`}>{copy.admin.actionRevoke}</button>
                            {m.status === "active" && !isSelf ? (
                              <button type="button" disabled={busy} onClick={() => run("disable", m, copy.admin.confirmDisable)} aria-label={`${m.username} ${copy.admin.actionDisable}`}>{copy.admin.actionDisable}</button>
                            ) : null}
                            {m.status === "disabled" ? (
                              <button type="button" disabled={busy} onClick={() => run("enable", m, copy.admin.confirmEnable)} aria-label={`${m.username} ${copy.admin.actionEnable}`}>{copy.admin.actionEnable}</button>
                            ) : null}
                            {!isSelf ? (
                              <button type="button" className="admin-actions__danger" disabled={busy} onClick={() => run("delete", m, copy.admin.confirmDelete)} aria-label={`${m.username} ${copy.admin.actionDelete}`}>{copy.admin.actionDelete}</button>
                            ) : null}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {editor ? (
        <form className="admin-editor" onSubmit={onEditorSubmit} aria-labelledby="admin-editor-title">
          <h2 id="admin-editor-title" className="admin-editor__title">
            {editor.kind === "rename" ? copy.admin.editorRenameTitle : copy.admin.editorResetTitle} — {editor.username}
          </h2>
          {editor.kind === "reset" ? <p className="login-form__hint">{copy.admin.editorResetHint}</p> : null}
          <div className="login-form__field">
            <label htmlFor="admin-editor-input">{editor.kind === "rename" ? copy.admin.nameLabel : copy.admin.newPasswordLabel}</label>
            <input id="admin-editor-input" type={editor.kind === "rename" ? "text" : "password"} autoComplete={editor.kind === "rename" ? "off" : "new-password"} value={editorValue} onChange={(e) => setEditorValue(e.target.value)} maxLength={editor.kind === "rename" ? 100 : 1024} required autoFocus />
          </div>
          <div className="admin-editor__buttons">
            <button type="submit" className="login-form__submit" disabled={busy}>{copy.admin.editorSave}</button>
            <button type="button" className="admin-editor__cancel" onClick={() => { setEditor(null); setEditorValue(""); }}>{copy.admin.editorCancel}</button>
          </div>
        </form>
      ) : null}

      <form className="admin-create" onSubmit={onCreate} aria-labelledby="admin-create-title">
        <h2 id="admin-create-title" className="admin-editor__title">{copy.admin.addTitle}</h2>
        <div className="login-form__field">
          <label htmlFor="admin-create-username">{copy.admin.usernameLabel}</label>
          <input id="admin-create-username" name="username" type="text" autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={64} required />
        </div>
        <div className="login-form__field">
          <label htmlFor="admin-create-name">{copy.admin.nameLabel}</label>
          <input id="admin-create-name" name="displayName" type="text" autoComplete="off" maxLength={100} required />
        </div>
        <div className="login-form__field">
          <label htmlFor="admin-create-password">{copy.admin.passwordLabel}</label>
          <input id="admin-create-password" name="password" type="password" autoComplete="new-password" maxLength={1024} required />
        </div>
        <div className="login-form__field">
          <label htmlFor="admin-create-role">{copy.admin.roleLabel}</label>
          <select id="admin-create-role" name="role" defaultValue="user">
            <option value="user">{copy.admin.roleUser}</option>
            <option value="admin">{copy.admin.roleAdmin}</option>
          </select>
        </div>
        <button type="submit" className="login-form__submit" disabled={busy}>{copy.admin.addSubmit}</button>
      </form>
    </div>
  );
}
