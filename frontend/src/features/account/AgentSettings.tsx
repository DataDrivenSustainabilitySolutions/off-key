import { useEffect, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/SettingsGroup";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConfirm } from "@/hooks/use-confirm";
import { createAgent, getAgents, revokeAgent, updateAgent, type Agent, type AgentStarts } from "@/lib/agent-api";
import { getApiUrl } from "@/lib/api-config";
import { getErrorMessage } from "@/lib/errors";

type Draft = { name: string; starts: AgentStarts };
type Issued = { name: string; key: string };

/** Where an agent that speaks MCP finds what its key may do, as tools. */
const MCP_ADDRESS = new URL(getApiUrl("/v1/mcp"), window.location.origin).href;
const HELP = `An agent signs in with a key in place of a password. Every key can read organization data, design and test monitors, and propose them to a member. Starting monitors is allowed per key: in shadow, where a monitor records its alarms and raises none, or live. Revoking a key stops it at once. An MCP client connects to ${MCP_ADDRESS} with a key as its bearer token.`;
/** What a key may start, from the least to the most. */
const LEVELS: { id: AgentStarts; label: string; means: string }[] = [
  { id: "nothing", label: "Proposes only", means: "proposes monitors for a member to start" },
  { id: "shadow", label: "Starts in shadow", means: "may start monitors in shadow, which record their alarms and raise none" },
  { id: "live", label: "Starts live", means: "may start monitors that raise alarms" },
];
const levels = LEVELS.map(level => <option key={level.id} value={level.id}>{level.label}</option>);
const meaning = (starts: AgentStarts) => LEVELS.find(level => level.id === starts)?.means ?? "";

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

  const create = ({ name, starts }: Draft) => run(async () => {
    const { key, ...agent } = await createAgent(name.trim(), starts);
    setAgents(current => [...current, agent]);
    setDraft(null);
    setCopied(false);
    setIssued({ name: agent.name, key });
    return "";
  });

  const allow = (agent: Agent, starts: AgentStarts) => run(async () => {
    const saved = await updateAgent(agent.id, starts);
    setAgents(current => current.map(entry => entry.id === saved.id ? saved : entry));
    return `${saved.name} ${meaning(saved.starts)}.`;
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
        onClick={() => { setError(""); setNotice(""); setDraft({ name: "", starts: "nothing" }); }}>New key</Button>}
      footer={<>
        {error && <p role="alert" className="text-destructive">{error}</p>}
        {notice && <p role="status">{notice}</p>}
      </>}>
      {draft && <form className="app-settings-invite" aria-label="New key"
        onSubmit={(event) => { event.preventDefault(); void create(draft); }}>
        <div className="grid min-w-0 flex-1 gap-1.5">
          <Label htmlFor="agent-name">Name</Label>
          <Input id="agent-name" required autoFocus autoComplete="off" maxLength={60} placeholder="Night shift agent" value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="agent-starts">Starting monitors</Label>
          <select id="agent-starts" className="app-settings-select" value={draft.starts}
            onChange={(event) => setDraft({ ...draft, starts: event.target.value as AgentStarts })}>{levels}</select>
        </div>
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
            <select aria-label={`Starting monitors for ${agent.name}`} className="app-settings-select" value={agent.starts} disabled={busy}
              onChange={(event) => void allow(agent, event.target.value as AgentStarts)}>{levels}</select>
            <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" disabled={busy}
              onClick={() => void revoke(agent)}>Revoke</Button>
          </SettingsRow>
        </li>)}
      </ul> : !draft && !issued && <SettingsRow label="No agent has a key yet" />}
    </SettingsGroup>
    {confirmation}
  </>;
}
