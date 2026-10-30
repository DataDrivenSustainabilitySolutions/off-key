import type { JsonValue } from "@/types/monitoring";

export function AdjacencyField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: JsonValue | undefined;
  disabled?: boolean;
  onChange: (value: JsonValue) => void;
}) {
  const graph =
    value && typeof value === "object" && !Array.isArray(value) ? value : {};
  return (
    <fieldset className="pl-field">
      <legend>{label}</legend>
      <p className="pl-help">
        Integer feature indices and their neighboring feature indices. Leave
        automatic enabled to use the model's default graph.
      </p>
      <label className="pl-check">
        <input
          type="checkbox"
          checked={value === null || value === undefined}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked ? null : {})}
        />
        Automatic graph
      </label>
      {Object.entries(graph).map(([node, neighbors]) => (
        <div key={node} className="pl-repeat-item">
          <label className="pl-field">
            <span>Feature index</span>
            <input
              type="number"
              step={1}
              disabled={disabled}
              value={node}
              aria-label={`${label} feature ${node}`}
              onChange={(event) => {
                const nextNode = event.target.value;
                if (
                  !/^-?\d+$/.test(nextNode) ||
                  (nextNode !== node &&
                    Object.prototype.hasOwnProperty.call(graph, nextNode))
                )
                  return;
                const next = { ...graph };
                delete next[node];
                next[nextNode] = neighbors;
                onChange(next);
              }}
            />
          </label>
          <div className="pl-number-list">
            {(Array.isArray(neighbors) ? neighbors : []).map(
              (neighbor, index) => (
                <div key={index}>
                  <input
                    type="number"
                    step={1}
                    value={String(neighbor)}
                    disabled={disabled}
                    aria-label={`${label} feature ${node} neighbor ${index + 1}`}
                    onChange={(event) =>
                      onChange({
                        ...graph,
                        [node]: (neighbors as JsonValue[]).map((item, at) =>
                          at === index ? Number(event.target.value) : item,
                        ),
                      })
                    }
                  />
                  {!disabled && (
                    <button
                      type="button"
                      aria-label={`Remove neighbor ${index + 1} from ${node}`}
                      onClick={() =>
                        onChange({
                          ...graph,
                          [node]: (neighbors as JsonValue[]).filter(
                            (_item, at) => at !== index,
                          ),
                        })
                      }
                    >
                      ×
                    </button>
                  )}
                </div>
              ),
            )}
          </div>
          {!disabled && (
            <>
              <button
                type="button"
                onClick={() =>
                  onChange({
                    ...graph,
                    [node]: [...(Array.isArray(neighbors) ? neighbors : []), 0],
                  })
                }
              >
                Add neighbor
              </button>
              <button
                type="button"
                onClick={() => {
                  const next = { ...graph };
                  delete next[node];
                  onChange(next);
                }}
              >
                Remove feature
              </button>
            </>
          )}
        </div>
      ))}
      {!disabled && value !== null && value !== undefined && (
        <button
          type="button"
          onClick={() => {
            let node = 0;
            while (Object.prototype.hasOwnProperty.call(graph, String(node)))
              node++;
            onChange({ ...graph, [node]: [] });
          }}
        >
          Add feature
        </button>
      )}
    </fieldset>
  );
}
