import { dataKinds, type DataKind } from "./semantics";

export function PipelineLegend({
  kinds,
  running,
  hasRuntimeState,
}: {
  kinds: DataKind[];
  running: boolean;
  hasRuntimeState: boolean;
}) {
  return (
    <div className="pl-graph-guide" aria-label="Graph language">
      <div className="pl-graph-direction">
        <strong>Data flow →</strong>
        <span>Aligned observations - explicit processing order</span>
      </div>
      <ul aria-label="Connection data types">
        {kinds.map((kind) => (
          <li key={kind} className={`pl-data--${kind}`}>
            <svg width="28" height="10" viewBox="0 0 28 10" aria-hidden="true">
              <path
                d="M0 5H23"
                stroke="currentColor"
                strokeWidth="2"
                strokeDasharray={dataKinds[kind].dash}
              />
              <path
                d="m22 1 5 4-5 4"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              />
            </svg>
            {dataKinds[kind].label}
          </li>
        ))}
      </ul>
      <p>
        {running
          ? `${hasRuntimeState ? "Runtime badges show the latest reported state." : "Waiting for reported node states."} Snapshot age and learning progress appear below.`
          : "Connections determine processing. Arrangement and node titles change the view. Configuration issues appear on their components."}
      </p>
    </div>
  );
}
