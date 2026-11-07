// "Доступ для агентов" (PN-15, ADR-0018): the user's agent tokens, issue and revoke.
// Only the page state holds an issued token; it is dropped on dismiss and never cached.
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { t } from "../../shared/i18n";
import { ConfirmDialog } from "../../shared/ui/ConfirmDialog";
import { ErrorAlert, useAlertState } from "../../shared/ui/ErrorAlert";
import { TextField } from "../../shared/ui/TextField";
import { useFocusHeadingOnArrival } from "../auth/session";
import {
  AGENT_TOKENS_KEY,
  createAgentToken,
  revokeAgentToken,
  useAgentTokens,
  type AgentToken,
  type CreatedAgentToken,
} from "./api";
import { IssuedToken } from "./IssuedToken";
import { TokenList } from "./TokenList";
import { failureMessage, nameProblem } from "./model";

export function AgentAccessPage() {
  const queryClient = useQueryClient();
  const alert = useAlertState();
  const tokens = useAgentTokens();
  const headingRef = useRef<HTMLHeadingElement>(null);
  useFocusHeadingOnArrival(headingRef);
  const nameRef = useRef<HTMLInputElement>(null);
  const listTitleRef = useRef<HTMLHeadingElement>(null);
  // One request at a time: a second submit or confirm while one is in flight is ignored.
  const busy = useRef(false);
  const [name, setName] = useState("");
  const [nameFailed, setNameFailed] = useState(false);
  const [pending, setPending] = useState(false);
  const [issued, setIssued] = useState<CreatedAgentToken | null>(null);
  const [confirming, setConfirming] = useState<AgentToken | null>(null);

  async function onCreate(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (busy.current) return;
    const problem = nameProblem(name);
    if (problem !== null) {
      setNameFailed(true);
      alert.show(t(problem));
      return;
    }
    busy.current = true;
    setPending(true);
    alert.clear();
    try {
      const created = await createAgentToken(name.trim());
      setIssued(created);
      setName("");
      setNameFailed(false);
    } catch (e) {
      alert.show(failureMessage(e));
    }
    await queryClient.invalidateQueries({ queryKey: AGENT_TOKENS_KEY });
    busy.current = false;
    setPending(false);
  }

  function dismissIssued(): void {
    setIssued(null);
    nameRef.current?.focus();
  }

  async function onRevoke(): Promise<void> {
    if (confirming === null || busy.current) return;
    busy.current = true;
    setPending(true);
    alert.clear();
    let revoked = false;
    try {
      await revokeAgentToken(confirming.id);
      revoked = true;
    } catch (e) {
      alert.show(failureMessage(e));
    }
    setConfirming(null);
    // The list is refreshed in both cases: a failed revoke may mean the token is already gone.
    await queryClient.invalidateQueries({ queryKey: AGENT_TOKENS_KEY });
    if (revoked) listTitleRef.current?.focus();
    busy.current = false;
    setPending(false);
  }

  const listError = tokens.isError && alert.message === null ? failureMessage(tokens.error) : null;
  const data = tokens.data;

  return (
    <section className="ui-wide">
      <h1 ref={headingRef} tabIndex={-1}>
        {t("agent_tokens.title")}
      </h1>
      <p>{t("agent_tokens.intro")}</p>
      <ErrorAlert message={alert.message ?? listError} seq={alert.seq} />

      {issued === null ? null : <IssuedToken key={issued.id} token={issued} onDismiss={dismissIssued} />}

      <h2>{t("agent_tokens.create_title")}</h2>
      <form onSubmit={(e) => void onCreate(e)} noValidate aria-label={t("agent_tokens.create_title")}>
        <TextField
          label={t("agent_tokens.name_label")}
          name="name"
          value={name}
          onChange={(value) => {
            setName(value);
            setNameFailed(false);
          }}
          autoComplete="off"
          hint={t("agent_tokens.name_hint")}
          invalid={nameFailed}
          inputRef={nameRef}
          disabled={pending}
        />
        <button type="submit" disabled={pending}>
          {t("agent_tokens.create_submit")}
        </button>
      </form>

      <h2 ref={listTitleRef} tabIndex={-1}>
        {t("agent_tokens.list_title")}
      </h2>
      {data === undefined ? (
        tokens.isPending ? (
          <p role="status">{t("agent_tokens.loading")}</p>
        ) : null
      ) : data.length === 0 ? (
        <p role="status">{t("agent_tokens.empty")}</p>
      ) : (
        <TokenList tokens={data} disabled={pending} onRevoke={setConfirming} />
      )}

      {confirming === null ? null : (
        <ConfirmDialog
          title={t("agent_tokens.revoke_title")}
          message={t("agent_tokens.revoke_message", { name: confirming.name })}
          pending={pending}
          onConfirm={() => void onRevoke()}
          onCancel={() => setConfirming(null)}
        />
      )}
    </section>
  );
}
