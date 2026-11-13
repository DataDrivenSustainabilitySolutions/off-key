import { useEffect, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/SettingsGroup";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConfirm } from "@/hooks/use-confirm";
import { createAgent, getAgents, revokeAgent, updateAgent, type Agent } from "@/lib/agent-api";
import { getApiUrl } from "@/lib/api-config";
import { getErrorMessage } from "@/lib/errors";

type Draft = { name: string; mayStart: boolean };
type Issued = { name: string; key: string };

/** Where an agent that speaks MCP finds what its key may do, as tools. */
const MCP_ADDRESS = new URL(getApiUrl("/v1/mcp"), window.location.origin).href;
const HELP = `An agent signs in with a key in place of a password. Every key can read organization data, design and test monitors, and propose them to a member. Starting monitors is allowed per key. Revoking a key stops it at once. An MCP client connects to ${MCP_ADDRESS} with a key as its bearer token.`;
const START = "May start monitors";

/** Keys for agents; members who manage members hand them out here. */
export function AgentSettings() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirm, confirmation] = useConfirm();

  useEffect(() => {
    let active = true;
    getAgents().then(list => { if (active) setAgents(list); })
      .catch(error => { if (active) setError(getErrorMessage(error)); });
    return () => { active = false; };
  }, []);

  const run = async (work: () => Promise<string>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      setNotice(await work());
    } catch (error) {
      setError(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const create = ({ name, mayStart }: Draft) => run(async () => {
    const { key, ...agent } = await createAgent(name.trim(), mayStart);
    setAgents(current => [...current, agent]);
    setDraft(null);
    setCopied(false);
    setIssued({ name: agent.name, key });
    return "";
  });

  const allow = (agent: Agent, mayStart: boolean) => run(async () => {
    const saved = await updateAgent(agent.id, mayStart);
    setAgents(current => current.map(entry => entry.id === saved.id ? saved : entry));
    return mayStart ? `${saved.name} may start monitors.` : `${saved.name} proposes monitors for a member to start.`;
  });

  const revoke = async (agent: Agent) => {
    if (!await confirm({ title: `Revoke the key of ${agent.name}?`,
      description: "The agent stops working at once. Monitors it started keep running. This cannot be undone.",
      confirmLabel: "Revoke key", destructive: true })) return;
    await run(async () => {
      await revokeAgent(agent.id);
      setAgents(current => current.filter(entry => entry.id !== agent.id));
      return `The key of ${agent.name} is revoked.`;
    });
  };

  const copy = async (key: string) => {
    try {
      await navigator.clipboard.writeText(key);
      setCopied(true);
    } catch {
      setError("The key could not be copied. Select it and copy it by hand.");
    }
  };

  return <>
    <SettingsGroup title="Agents" help={HELP}
      actions={!draft && !issued && <Button variant="outline" size="sm" disabled={busy}
        onClick={() => { setError(""); setNotice(""); setDraft({ name: "", mayStart: false }); }}>New key</Button>}
      footer={<>
        {error && <p role="alert" className="text-destructive">{error}</p>}
        {notice && <p role="status">{notice}</p>}
      </>}>
      {draft && <form className="app-settings-invite app-settings-role-form" aria-label="New key"
        onSubmit={(event) => { event.preventDefault(); void create(draft); }}>
        <div className="grid min-w-0 flex-1 gap-1.5">
          <Label htmlFor="agent-name">Name</Label>
          <Input id="agent-name" required autoFocus autoComplete="off" maxLength={60} placeholder="Night shift agent" value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </div>
        <label className="app-settings-permission">
          <input type="checkbox" checked={draft.mayStart} onChange={(event) => setDraft({ ...draft, mayStart: event.target.checked })} />
          <span><span className="app-settings-permission-name">{START}</span>
            <span className="app-settings-row-detail">Without this, the agent proposes a monitor and a member starts it.</span></span>
        </label>
        <div className="flex gap-2">
          <Button disabled={busy} type="submit">Create key</Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => setDraft(null)}>Cancel</Button>
        </div>
      </form>}
      {issued && <div className="app-settings-invite app-settings-role-form" role="group" aria-label={`Key of ${issued.name}`}>
        <div className="grid min-w-0 flex-1 gap-1.5">
          <Label htmlFor="agent-key">Key of {issued.name}</Label>
          <Input id="agent-key" readOnly className="font-mono" value={issued.key} onFocus={(event) => event.target.select()} />
          <p className="app-settings-row-detail">Copy the key now. It is not shown again. An MCP client
            connects to <span className="font-mono break-all">{MCP_ADDRESS}</span> with it as its bearer token.</p>
        </div>
        <div className="flex gap-2">
          <Button type="button" onClick={() => void copy(issued.key)}>{copied ? "Copied" : "Copy key"}</Button>
          <Button type="button" variant="ghost" onClick={() => setIssued(null)}>Done</Button>
        </div>
      </div>}
      {agents.length ? <ul aria-label="Agents" className="app-settings-list">
        {agents.map(agent => <li key={agent.id}>
          <SettingsRow className="is-wrapping" label={agent.name}
            detail={`Key ending in ${agent.key_hint}${agent.created_by ? ` · Created by ${agent.created_by}` : ""}`}>
            <label className="app-settings-check">
              <input type="checkbox" checked={agent.may_start} disabled={busy} aria-label={`${agent.name} may start monitors`}
                onChange={(event) => void allow(agent, event.target.checked)} />
              {START}
            </label>
            <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" disabled={busy}
              onClick={() => void revoke(agent)}>Revoke</Button>
          </SettingsRow>
        </li>)}
      </ul> : !draft && !issued && <SettingsRow label="No agent has a key yet" />}
    </SettingsGroup>
    {confirmation}
  </>;
}
