import { useId } from "react";
import { Link } from "react-router-dom";
import { PIPELINE_LIMITS } from "@/types/pipelines.generated";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";

export function PipelineReadingPicker({ target, selected, disabled, owned, onChange, recordingHref }: {
  target?: MonitoringTarget; selected: string[]; disabled: boolean;
  owned: (id: string) => boolean; onChange: (selected: string[]) => void;
  /** Where recording is turned on for the given readings. */
  recordingHref?: (readingIds: string[]) => string;
}) {
  const descriptionId = useId();
  if (!target) return null;
  const available = target.inputs.filter((input) => input.binding.policy.mode !== "off" && !owned(input.stream.id));
  const unrecorded = target.inputs.filter((input) => input.binding.policy.mode === "off").map((input) => input.stream.id);
  return <fieldset className="pl-reading-picker" disabled={disabled}>
    <legend>Readings to monitor</legend>
    <div className="pl-reading-actions">
      <p className="pl-help">Check only the readings this service should use.</p>
      <button type="button" disabled={!available.length} onClick={() => onChange(available.slice(0, PIPELINE_LIMITS.slots).map((input) => input.stream.id))}>Select all available</button>
      <button type="button" disabled={!selected.length} onClick={() => onChange([])}>Clear</button>
    </div>
    {unrecorded.length > 0 && <p className="pl-notice" role="status">
      {unrecorded.length === target.inputs.length ? "None of these readings is recorded yet, so none can be selected."
        : `${unrecorded.length} of ${target.inputs.length} readings are not recorded and cannot be selected.`}
      {" "}A service learns from recorded readings; live data alone is not enough.
      {recordingHref && <> <Link to={recordingHref(unrecorded)}>Turn on recording in Sources</Link></>}
    </p>}
    <div className="pl-reading-options">
      {target.inputs.map((input, index) => {
        const checked = selected.includes(input.stream.id);
        const reason = input.binding.policy.mode === "off" ? "Not recorded" : owned(input.stream.id) ? "Already monitored"
          : !checked && selected.length >= PIPELINE_LIMITS.slots ? `${PIPELINE_LIMITS.slots} reading limit` : "";
        const description = [input.stream.unit, reason].filter(Boolean).join(" · ");
        return <label className="pl-reading-option" key={input.stream.id}>
          <input type="checkbox" aria-label={`Monitor ${input.stream.label}`} aria-describedby={description ? `${descriptionId}-${index}` : undefined}
            checked={checked} disabled={!checked && !!reason}
            onChange={(event) => onChange(event.target.checked ? [...selected, input.stream.id] : selected.filter((id) => id !== input.stream.id))} />
          <span>{input.stream.label}{description && <small id={`${descriptionId}-${index}`}>{description}</small>}</span>
        </label>;
      })}
    </div>
  </fieldset>;
}
