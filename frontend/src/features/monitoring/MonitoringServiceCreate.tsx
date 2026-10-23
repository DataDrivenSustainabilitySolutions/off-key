import { useEffect, useMemo, useState } from "react";
import { useNavigationDraft } from "@/lib/navigation-draft";
import { Link, useLocation } from "react-router-dom";
import { sourceHref } from "@/domain/system/collectionRules";
import type { SystemDocument } from "@/types/system";
import { Breadcrumb } from "@/components/Breadcrumb";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";
import { getErrorMessage } from "@/lib/errors";
import { AdaptiveMonitoringSetup } from "./setup/AdaptiveMonitoringSetup";
import { StaticMonitoringSetup } from "./setup/StaticMonitoringSetup";
import type { ActiveService, ModelDefinition, MonitoringStrategy } from "@/types/monitoring";
import { MonitoringTargetPicker } from "../workspace/MonitoringTargetPicker";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";

type Props = { targets: MonitoringTarget[]; services: ActiveService[]; initialTarget?: string; initialReading?: string;
  byStream: Map<string, Set<string>>; collectionReady: boolean; document?: SystemDocument; draftKey?: string; onStarted: (id?: string) => Promise<void>; onBack: () => void };

export function MonitoringServiceCreate({ targets, services, initialTarget, initialReading, byStream, collectionReady, document, draftKey, onStarted, onBack }: Props) {
  const location = useLocation();
  const [targetId, setTargetId] = useNavigationDraft(draftKey && `${draftKey}:target`, initialTarget);
  const [name, setName] = useNavigationDraft(draftKey && `${draftKey}:name`, "");
  const [strategy, setStrategy] = useNavigationDraft<MonitoringStrategy>(draftKey && `${draftKey}:strategy`, "adaptive_stream");
  const [models, setModels] = useState<Record<string, ModelDefinition>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const target = targets.find(item => item.id === targetId);
  const collectionIds = useMemo(() => target?.inputs.some(input => input.stream.id === initialReading)
    ? [initialReading!] : target?.inputs.map(input => input.stream.id) ?? [], [target, initialReading]);
  const enabledInputs = useMemo(() => target?.inputs.filter(input => input.binding.policy.mode !== "off") ?? [], [target]);
  const sensors = useMemo(() => enabledInputs.map(input => input.binding.telemetry_key), [enabledInputs]);
  const sensorLabels = useMemo(() => new Map(enabledInputs.map(input => [input.binding.telemetry_key, input.stream.label])), [enabledInputs]);
  const sensorTopics = useMemo(() => new Map(enabledInputs.map(input => [input.binding.telemetry_key, input.binding.accepted_topic])), [enabledInputs]);
  const claims = useMemo(() => {
    const owners = new Map<string, ActiveService>();
    const active = new Map(services.filter(service => service.status).map(service => [service.id, service]));
    for (const input of enabledInputs) {
      for (const id of byStream.get(input.stream.id) ?? []) {
        const service = active.get(id);
        if (service) owners.set(input.binding.telemetry_key, service);
      }
    }
    return owners;
  }, [enabledInputs, services, byStream]);
  const availableModels = useMemo(() => Object.fromEntries(Object.entries(models).filter(([, model]) => model.strategy === strategy)), [models, strategy]);
  useEffect(() => {
    const controller = new AbortController();
    void apiUtils.get<Record<string, ModelDefinition>>(API_CONFIG.ENDPOINTS.MONITORING.MODELS, { signal: controller.signal, redirectOnUnauthorized: false })
      .then(result => { if (!controller.signal.aborted) { setModels(result); setLoading(false); setError(""); } }, reason => {
        if (!controller.signal.aborted) { setError(getErrorMessage(reason)); setLoading(false); }
      });
    return () => controller.abort();
  }, [retry]);
  const displayName = name.trim() || `${target?.label ?? "Monitoring"} · ${strategy === "adaptive_stream" ? "Adaptive" : "Static"}`;
  const props = { draftKey: draftKey && `${draftKey}:${targetId}:${strategy}`, chargerId: target?.id ?? "", sensorTypes: sensors, claimsBySensor: claims, loadingModels: loading || !collectionReady,
    onStarted, displayName, initialReading: target?.inputs.find(input => input.stream.id === initialReading)?.binding.telemetry_key, sensorLabels, sensorTopics };
  return <section className="mn-create" aria-label="Create monitoring service">
    <Breadcrumb steps={[{ label: "Monitoring", onClick: onBack }]} current="New service" />
    <div className="mn-detail-header"><div><h1>Create service</h1></div></div>
    <p className="ex-muted">Visual flow editing is disabled for this deployment.</p>
    <div className="mn-create-fields"><label className="mn-field">Name<input aria-label="Service name" maxLength={120} placeholder="e.g. Machine health" value={name} onChange={event => setName(event.target.value)} /></label>
      <div className="mn-field"><span>Inputs</span><MonitoringTargetPicker targets={targets} value={targetId} onChange={id => { setTargetId(id); }} /></div></div>
    {!targets.length && <p className="ex-muted">Add numeric readings to the catalogue to configure monitoring.</p>}
    {target && <>
      <p className="ex-muted">{enabledInputs.length} recorded readings · <Link className="ex-collection-monitor" to={sourceHref(collectionIds, document, `${location.pathname}${location.search}`)}>Configure in Sources</Link></p>
      {enabledInputs.length ? <>
        {!collectionReady && <p className="ex-muted">Waiting for collection to apply…</p>}
        <div className="mn-create-mode" aria-label="Monitoring strategy"><button aria-pressed={strategy === "adaptive_stream"} onClick={() => setStrategy("adaptive_stream")}>Adaptive stream</button>
          <button aria-pressed={strategy === "static_baseline"} onClick={() => setStrategy("static_baseline")}>Static baseline</button></div>
        {error && <p className="ex-preview-error" role="alert">{error}<button onClick={() => { setLoading(true); setRetry(value => value + 1); }}>Retry</button></p>}
        {strategy === "adaptive_stream" ? <AdaptiveMonitoringSetup key={`${target.id}:${initialReading ?? ""}`} {...props} adaptiveModels={availableModels} />
          : <StaticMonitoringSetup key={`${target.id}:${initialReading ?? ""}`} {...props} staticModels={availableModels} />}
      </> : <p className="ex-muted">Enable collection for the readings this service will monitor.</p>}
    </>}
  </section>;
}
