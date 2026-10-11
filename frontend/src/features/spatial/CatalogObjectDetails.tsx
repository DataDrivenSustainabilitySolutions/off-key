import { FileJson, Radio } from "lucide-react";
import type { SpatialNode } from "./types";

export function CatalogObjectDetails({
  node,
  related,
  onSelect,
}: {
  node: SpatialNode;
  related: readonly SpatialNode[];
  onSelect: (id: string) => void;
}) {
  const definition = node.catalog;
  if (!definition) return null;
  const sensors = related.filter((item) => item.kind === "sensor");
  const policy =
    definition.collectionMode === "sample"
      ? `Sample every ${definition.intervalSeconds} seconds`
      : definition.collectionMode === "original"
        ? "Original rate"
        : "Off";
  return (
    <section className="sp-catalog-definition">
      <div className="sp-section-title">
        <h3>Catalog definition</h3>
        <FileJson size={14} />
      </div>
      <dl>
        {definition.valueType && (
          <>
            <dt>Value type</dt>
            <dd>
              {definition.valueType === "number"
                ? "Numeric"
                : definition.valueType === "boolean"
                  ? "Boolean state"
                  : definition.valueType === "identifier"
                    ? "Identifier"
                    : "Text"}
            </dd>
          </>
        )}
        {definition.category && (
          <>
            <dt>Category</dt>
            <dd>{definition.category}</dd>
          </>
        )}
        {node.kind === "sensor" && (
          <>
            <dt>Unit</dt>
            <dd>{node.unit || "Not specified"}</dd>
          </>
        )}
        {definition.collectionMode && (
          <>
            <dt>Collection</dt>
            <dd>{policy}</dd>
          </>
        )}
        {node.kind !== "sensor" && (
          <>
            <dt>Defined topics</dt>
            <dd>{sensors.length}</dd>
          </>
        )}
      </dl>
      {definition.upstreamTopic && (
        <div className="sp-catalog-topic">
          <span>Upstream MQTT topic</span>
          <code>{definition.upstreamTopic}</code>
        </div>
      )}
      {sensors.length > 0 && node.kind !== "sensor" && (
        <div className="sp-catalog-topics">
          <h3>Topics</h3>
          {sensors.map((sensor) => (
            <button key={sensor.id} onClick={() => onSelect(sensor.id)}>
              <Radio size={13} />
              <span>{sensor.label}</span>
              <small>
                {sensor.catalog?.valueType === "number"
                  ? "123"
                  : sensor.catalog?.valueType === "boolean"
                    ? "0/1"
                    : "Aa"}
              </small>
            </button>
          ))}
        </div>
      )}
      <details>
        <summary>Stable identifiers</summary>
        <dl>
          <dt>Broker</dt>
          <dd>
            <code>{definition.sourceId}</code>
          </dd>
          {definition.chargerId && (
            <>
              <dt>Charger</dt>
              <dd>
                <code>{definition.chargerId}</code>
              </dd>
            </>
          )}
          {definition.sensorKey && (
            <>
              <dt>Sensor key</dt>
              <dd>
                <code>{definition.sensorKey}</code>
              </dd>
            </>
          )}
        </dl>
      </details>
      <p>
        Imported configuration only. Collection Off describes the catalog
        policy, not whether a device is online.
      </p>
    </section>
  );
}
