import type { PipelineComponent, PipelineNode } from "./contracts";
import { checkpointRows, NO_FORECAST_SERVICE, sizeText, stateText, type ForecastModels } from "./forecastModels";
import { setting } from "./scope";

/** The checkpoints a pretrained forecaster can use and whether the forecast service
 * holds each one's weights. A monitor scores nothing until its checkpoint is there,
 * so the weights can be fetched here, before it starts. */
export function PipelineForecastModels({ node, component, forecast }: {
  node: PipelineNode;
  component: PipelineComponent;
  forecast: ForecastModels;
}) {
  const { catalog, error, download, refresh } = forecast;
  const retry = <button type="button" onClick={refresh}>Check again</button>;
  const body = () => {
    if (!catalog) return error
      ? <p className="pl-warning" role="status">The state of the model weights could not be read. {error} {retry}</p>
      : <p className="pl-help" role="status">Checking the model weights…</p>;
    if (catalog.service === "not_deployed")
      return <p className="pl-warning" role="status">{NO_FORECAST_SERVICE} A monitor with this step cannot start here.</p>;
    if (catalog.service === "unreachable") return <p className="pl-warning" role="status">
      The forecast service does not answer right now, so the state of the weights is unknown. {retry}
    </p>;
    const selected = setting(node, component, "checkpoint");
    return <>
      <ul className="pl-forecast-models">
        {checkpointRows(component, catalog).map(({ id, label, model }) => {
          const size = model && sizeText(model.download_bytes);
          const startable = model?.status === "not_downloaded" || model?.status === "failed";
          return <li key={id} className={id === selected ? "is-selected" : undefined}>
            <span className="pl-forecast-model">
              <strong>{label}</strong>
              <small>{[size, id === selected ? "used by this step" : ""].filter(Boolean).join(" · ")}</small>
            </span>
            <span className={`pl-forecast-state is-${model?.status ?? "missing"}`}>{stateText(model)}</span>
            {startable && <button type="button" aria-label={`${model.status === "failed" ? "Try again to download" : "Download"} ${label}`}
              onClick={() => download(id)}>{model.status === "failed" ? "Try again" : "Download"}</button>}
            {model?.status === "downloading" && <progress aria-label={`Download of ${label}`} max={1}
              {...(model.progress == null ? {} : { value: model.progress })} />}
            {model?.status === "failed" && model.error && <small className="pl-forecast-error">{model.error}</small>}
          </li>;
        })}
      </ul>
      {error && <p className="pl-error" role="alert">The download did not start. {error}</p>}
      <small className="pl-help">
        The forecast service downloads a checkpoint's weights once and keeps them. A monitor that starts before
        its checkpoint is ready scores nothing until the download ends.
      </small>
    </>;
  };
  return <div className="pl-field" role="group" aria-label="Model weights">
    <span>Model weights</span>
    {body()}
  </div>;
}
