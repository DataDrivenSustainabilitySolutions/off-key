import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { getErrorMessage } from "@/lib/errors";
import { ApiRequestError } from "@/lib/api-client";
import { useAuth } from "@/auth/AuthContext";
import { useNavigationDraft } from "@/lib/navigation-draft";
import type { ActiveService } from "@/types/monitoring";
import type { PipelineActivationView } from "@/types/pipelines.generated";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import { MonitoringTargetPicker } from "../workspace/MonitoringTargetPicker";
import { sourceHref } from "@/domain/system/collectionRules";
import { useCatalogue } from "../workspace/catalogue-context";
import type { PipelineDefinition, PipelineRevisionView } from "./contracts";
import { executableChanges } from "./model";
import { pipelinesApi } from "./api";
import { strategyLabel } from "./semantics";
import { readingOwnedElsewhere } from "./bindings";
import {
  readActivationRequest,
  retainActivationRequest,
} from "./activationRequest";

type Props = {
  revision: PipelineRevisionView;
  previous?: PipelineDefinition;
  previousBindings?: Record<string, string>;
  replaceService?: ActiveService;
  targets: MonitoringTarget[];
  services: ActiveService[];
  byStream: Map<string, Set<string>>;
  initialTarget?: string;
  initialReading?: string;
  defaultName: string;
  collectionReady: boolean;
  onClose: () => void;
  onComplete: (serviceId: string) => void;
  operationId?: string;
  onOperation: (id: string) => void;
};

const terminal = new Set(["succeeded", "failed", "cancelled"]);
type ReviewDraft = {
  targetId: string | undefined;
  bindings: Record<string, string>;
  name: string;
};

export function PipelineActivation({
  revision,
  previous,
  previousBindings,
  replaceService,
  targets,
  services,
  byStream,
  initialTarget,
  initialReading,
  defaultName,
  collectionReady,
  onClose,
  onComplete,
  operationId,
  onOperation,
}: Props) {
  const { document } = useCatalogue();
  const { userId } = useAuth();
  const location = useLocation();
  const requestKey = `pipeline-activation:${userId}:${revision.id}:${replaceService?.id ?? "new"}`;
  const [pending, setPending] = useState(() =>
    readActivationRequest(requestKey),
  );
  const [review, setReview] = useNavigationDraft<ReviewDraft>(
    `${requestKey}:review:${initialTarget ?? initialReading ?? "library"}`,
    () => ({
      targetId:
        initialTarget ??
        targets.find((target) =>
          target.inputs.some(
            (input) =>
              input.stream.id ===
              (initialReading ??
                Object.values(pending?.bindings ?? previousBindings ?? {})[0]),
          ),
        )?.id,
      bindings:
        pending?.bindings ??
        previousBindings ??
        (initialReading && revision.definition.input_slots[0]
          ? { [revision.definition.input_slots[0].id]: initialReading }
          : {}),
      name:
        pending?.display_name ?? replaceService?.display_name ?? defaultName,
    }),
  );
  const targetId = pending
    ? targets.find((target) =>
        target.inputs.some((input) =>
          Object.values(pending.bindings).includes(input.stream.id),
        ),
      )?.id
    : review.targetId;
  const bindings = pending?.bindings ?? review.bindings;
  const name = pending?.display_name ?? review.name;
  const [confirmed, setConfirmed] = useState(!!pending);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [operation, setOperation] = useState<PipelineActivationView>();
  const key = useRef<string | null>(null);
  const target = targets.find((item) => item.id === targetId);
  const owned = readingOwnedElsewhere(services, byStream, replaceService?.id);
  const completeBindings =
    revision.definition.input_slots.every((slot) => {
      const reading = target?.inputs.find(
        (input) => input.stream.id === bindings[slot.id],
      );
      return (
        reading &&
        reading.binding.policy.mode !== "off" &&
        !owned(reading.stream.id) &&
        (!slot.unit || reading.stream.unit === slot.unit)
      );
    }) &&
    new Set(Object.values(bindings)).size ===
      revision.definition.input_slots.length;
  const changes = previous
    ? executableChanges(previous, revision.definition)
    : [];
  const operationPhase = operation?.phase;
  useEffect(() => {
    if (!operationId) return;
    const controller = new AbortController();
    let pending = false;
    const poll = async () => {
      if (pending || window.document.hidden) return;
      pending = true;
      try {
        const next = await pipelinesApi.activation(
          operationId,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setOperation(next);
          setError("");
          if (next.phase === "succeeded") onComplete(next.service_id);
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(getErrorMessage(reason));
      } finally {
        pending = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => {
      if (!operationPhase || !terminal.has(operationPhase)) void poll();
    }, 3_000);
    const visible = () => void poll();
    window.document.addEventListener("visibilitychange", visible);
    return () => {
      controller.abort();
      clearInterval(timer);
      window.document.removeEventListener("visibilitychange", visible);
    };
  }, [operationId, operationPhase, onComplete]);
  const activate = async () => {
    if (
      busy ||
      (!pending && (!completeBindings || !confirmed || !collectionReady))
    )
      return;
    setBusy(true);
    setError("");
    if (!key.current) key.current = crypto.randomUUID();
    const request = pending ?? {
      revision_id: revision.id,
      bindings,
      display_name: name.trim(),
      idempotency_key: key.current,
      replace_service_id: replaceService?.id ?? null,
    };
    setPending(request);
    retainActivationRequest(requestKey, request);
    try {
      const next = await pipelinesApi.activate(request);
      retainActivationRequest(requestKey);
      setPending(undefined);
      setOperation(next);
      onOperation(next.id);
      if (next.phase === "succeeded") onComplete(next.service_id);
    } catch (reason) {
      if (
        reason instanceof ApiRequestError &&
        reason.status !== undefined &&
        reason.status < 500
      ) {
        retainActivationRequest(requestKey);
        setPending(undefined);
        key.current = null;
      }
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="pl-activation" aria-label="Review pipeline activation">
      <div className="pl-header">
        <h3>
          {replaceService ? "Replace monitoring run" : "Start monitoring run"}
        </h3>
        <button type="button" onClick={onClose}>
          Close review
        </button>
      </div>
      {error && (
        <p className="pl-error" role="alert">
          {error}
        </p>
      )}
      {operation ? (
        <>
          <p role="status">Activation {operation.phase.replace(/_/g, " ")}</p>
          <p className="pl-help">
            Operation {operation.id} · resulting service {operation.service_id}
          </p>
          {operation.error && (
            <p role="alert" className="pl-error">
              {operation.error}
            </p>
          )}
          {!terminal.has(operation.phase) && (
            <button
              type="button"
              disabled={busy || operation.phase === "cancelling"}
              onClick={async () => {
                setBusy(true);
                try {
                  setOperation(await pipelinesApi.cancel(operation.id));
                } catch (reason) {
                  setError(getErrorMessage(reason));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Cancel activation
            </button>
          )}
          {operation.phase === "failed" && (
            <p>
              The previous run is not restarted automatically. Review the
              failure before starting another activation.
            </p>
          )}
        </>
      ) : (
        <>
          <p>
            Revision {revision.number} ·{" "}
            {strategyLabel(revision.definition.strategy)}
          </p>
          {previous && (
            <>
              <h4>Processing changes</h4>
              {changes.length ? (
                <ul>
                  {changes.map((change, index) => (
                    <li key={index}>{change}</li>
                  ))}
                </ul>
              ) : (
                <p>
                  No processing changes. Activation still creates a fresh run.
                </p>
              )}
            </>
          )}
          {pending && !busy && (
            <p className="pl-warning" role="status">
              The activation response was not confirmed. Recover the same
              request before changing its configuration.
            </p>
          )}
          <fieldset
            className="pl-activation-fields"
            disabled={busy || !!pending}
          >
            <label className="pl-field">
              <span>Service name</span>
              <input
                maxLength={120}
                required
                value={name}
                onChange={(event) => {
                  setReview((current) => ({
                    ...current,
                    name: event.target.value,
                  }));
                  key.current = null;
                }}
              />
            </label>
            <div className="pl-field">
              <span>Input source</span>
              <MonitoringTargetPicker
                targets={targets}
                value={targetId}
                onChange={(id) => {
                  setReview((current) => ({
                    ...current,
                    targetId: id,
                    bindings: {},
                  }));
                  setConfirmed(false);
                  key.current = null;
                }}
              />
            </div>
            {revision.definition.input_slots.map((slot) => (
              <label key={slot.id} className="pl-field">
                <span>
                  {slot.label}
                  {slot.unit
                    ? ` · expected ${slot.unit}`
                    : " · unit unspecified"}
                </span>
                <select
                  value={bindings[slot.id] ?? ""}
                  onChange={(event) => {
                    setReview((current) => ({
                      ...current,
                      bindings: {
                        ...current.bindings,
                        [slot.id]: event.target.value,
                      },
                    }));
                    setConfirmed(false);
                    key.current = null;
                  }}
                >
                  <option value="">Bind a numeric reading</option>
                  {target?.inputs.map((input) => (
                    <option
                      key={input.stream.id}
                      value={input.stream.id}
                      disabled={
                        input.binding.policy.mode === "off" ||
                        owned(input.stream.id) ||
                        (!!slot.unit && input.stream.unit !== slot.unit) ||
                        Object.entries(bindings).some(
                          ([id, reading]) =>
                            id !== slot.id && reading === input.stream.id,
                        )
                      }
                    >
                      {input.stream.label}
                      {input.stream.unit
                        ? ` (${input.stream.unit})`
                        : " (unit unspecified)"}
                      {input.binding.policy.mode === "off"
                        ? " · collection off"
                        : owned(input.stream.id)
                          ? " · already monitored"
                          : ""}
                    </option>
                  ))}
                </select>
                {previousBindings?.[slot.id] &&
                  previousBindings[slot.id] !== bindings[slot.id] && (
                    <small>
                      Binding changed from{" "}
                      {document.streams.find(
                        (input) => input.id === previousBindings[slot.id],
                      )?.label ?? previousBindings[slot.id]}
                    </small>
                  )}
              </label>
            ))}
            <Link
              to={sourceHref(
                target?.inputs.map((input) => input.stream.id) ?? [],
                document,
                `${location.pathname}${location.search}`,
              )}
            >
              Configure collection in Sources
            </Link>
            {!collectionReady && (
              <p role="status" className="pl-warning">
                Waiting for collection to apply. Activation will be available
                when the selected collection revision is acknowledged.
              </p>
            )}
            {replaceService && (
              <p className="pl-warning">
                Activation stops “
                {replaceService.display_name ?? replaceService.container_name}”
                before starting the successor. Monitoring is interrupted during
                replacement and fresh learning/calibration.
              </p>
            )}
            <label className="pl-check">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              I reviewed the input bindings
              {replaceService
                ? " and the interruption caused by replacement"
                : " and revision"}
              .
            </label>
          </fieldset>
          <div className="pl-actions">
            <button
              type="button"
              className="mn-primary"
              disabled={
                busy ||
                (!pending &&
                  (!completeBindings ||
                    !confirmed ||
                    !name.trim() ||
                    !collectionReady))
              }
              onClick={() => void activate()}
            >
              {busy
                ? "Submitting…"
                : pending
                  ? "Recover activation request"
                  : replaceService
                    ? "Activate replacement"
                    : "Start revision"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
