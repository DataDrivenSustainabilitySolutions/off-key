import { useId, useMemo, useState, useSyncExternalStore } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import type { SystemLiveTelemetry } from "./systemLiveTelemetry";
import type { LiveNodeSnapshot } from "./systemLiveTypes";
import type { SystemStream } from "./systemTypes";
import "./systemTopicBrowser.css";

const TOPICS_PER_PAGE = 12;
const READINGS_PER_PAGE = 8;
const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 });
const noSubscription = () => () => {};
const noSnapshot = () => undefined;
const count = (value: number, noun: string) =>
  `${value} ${noun}${value === 1 ? "" : "s"}`;
type Topic = {
  key: string;
  path: string;
  readings: SystemStream[];
  total: number;
};
type Props = {
  streams: readonly SystemStream[];
  onSelect: (id: string) => void;
  selectedStreamId?: string;
  telemetry?: SystemLiveTelemetry;
};

/** MQTT topic identity includes its broker; JSON fields remain separate readings. */
function groupTopics(streams: readonly SystemStream[]): Topic[] {
  const topics = new Map<string, Topic>();
  for (const stream of streams) {
    const key = JSON.stringify([stream.connection_id, stream.topic]);
    let topic = topics.get(key);
    if (!topic) {
      topic = { key, path: stream.topic, readings: [], total: 0 };
      topics.set(key, topic);
    }
    topic.readings.push(stream);
    topic.total++;
  }
  return [...topics.values()];
}

function Value({
  snapshot,
  unit,
}: {
  snapshot: LiveNodeSnapshot | undefined;
  unit?: string;
}) {
  const value = snapshot?.latestValue;
  const text =
    value == null
      ? "—"
      : typeof value === "number"
        ? number.format(value)
        : String(value);
  return (
    <span
      className={`sp-topic-value${snapshot?.retained ? " is-retained" : ""}`}
      title={`${text}${unit && typeof value === "number" ? ` ${unit}` : ""}${snapshot?.retained ? " · Retained reading" : ""}`}
    >
      {text}
      {unit && typeof value === "number" && <small>{unit}</small>}
      {snapshot?.retained && (
        <span className="sp-topic-retained" aria-label="Retained reading">
          R
        </span>
      )}
    </span>
  );
}

function Reading({
  stream,
  onSelect,
  selected,
  snapshot,
  showValue,
  topicPath,
}: {
  stream: SystemStream;
  onSelect: (id: string) => void;
  selected: boolean;
  snapshot?: LiveNodeSnapshot;
  showValue: boolean;
  topicPath?: string;
}) {
  return (
    <button
      className={`sp-topic-reading${selected ? " is-selected" : ""}`}
      aria-label={`Inspect ${stream.label} on ${stream.topic}`}
      aria-current={selected ? "true" : undefined}
      onClick={() => onSelect(stream.id)}
    >
      <span className="sp-topic-reading-identity">
        {topicPath && <code title={topicPath}>{topicPath}</code>}
        <span>{stream.label}</span>
        <small title={stream.payload_pointer ?? "Whole MQTT payload"}>
          {stream.payload_pointer || "Payload"} · {stream.value_type}
        </small>
      </span>
      {showValue && <Value snapshot={snapshot} unit={stream.unit} />}
    </button>
  );
}

function TopicRow({
  topic,
  selectedStreamId,
  onSelect,
  telemetry,
  showValues,
}: {
  topic: Topic;
  selectedStreamId?: string;
  onSelect: (id: string) => void;
  telemetry?: SystemLiveTelemetry;
  showValues: boolean;
}) {
  const selectedIndex = topic.readings.findIndex(
    (stream) => stream.id === selectedStreamId,
  );
  const [expanded, setExpanded] = useState(selectedIndex >= 0);
  const [readingPage, setReadingPage] = useState(() =>
    Math.max(0, Math.floor(selectedIndex / READINGS_PER_PAGE)),
  );
  const region = useId();
  const totalPages = Math.ceil(topic.readings.length / READINGS_PER_PAGE);
  const page = Math.min(readingPage, Math.max(0, totalPages - 1));
  const start = page * READINGS_PER_PAGE;
  const matching = topic.readings.length;
  if (topic.total === 1) {
    const stream = topic.readings[0]!;
    return (
      <div className="sp-topic-row sp-topic-single">
        <Reading
          stream={stream}
          selected={selectedIndex >= 0}
          onSelect={onSelect}
          showValue={showValues}
          topicPath={topic.path}
          snapshot={showValues ? telemetry?.getSnapshot(stream.id) : undefined}
        />
      </div>
    );
  }
  return (
    <div className="sp-topic-row">
      <button
        className="sp-topic-toggle"
        aria-label={`${expanded ? "Collapse" : "Expand"} topic ${topic.path}`}
        aria-expanded={expanded}
        aria-controls={region}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span>
          <code title={topic.path}>{topic.path}</code>
          <small>
            {matching === topic.total
              ? `${topic.total} readings`
              : `${matching} of ${topic.total} readings match`}
          </small>
        </span>
      </button>
      {expanded && (
        <div className="sp-topic-fields" id={region}>
          {topic.readings
            .slice(start, start + READINGS_PER_PAGE)
            .map((stream) => (
              <Reading
                key={stream.id}
                stream={stream}
                selected={stream.id === selectedStreamId}
                onSelect={onSelect}
                showValue={showValues}
                snapshot={
                  showValues ? telemetry?.getSnapshot(stream.id) : undefined
                }
              />
            ))}
          {totalPages > 1 && (
            <div
              className="sp-topic-pages sp-topic-field-pages"
              aria-label={`Readings in ${topic.path}`}
            >
              <button
                aria-label={`Previous readings in ${topic.path}`}
                disabled={page === 0}
                onClick={() => setReadingPage(page - 1)}
              >
                <ChevronLeft size={12} />
              </button>
              <span>
                {start + 1}–{Math.min(start + READINGS_PER_PAGE, matching)} of{" "}
                {matching}
              </span>
              <button
                aria-label={`Next readings in ${topic.path}`}
                disabled={page === totalPages - 1}
                onClick={() => setReadingPage(page + 1)}
              >
                <ChevronRight size={12} />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** One shared subscription and bounded topic/field pages; charts open only on selection. */
export function SystemTopicBrowser({
  streams,
  onSelect,
  selectedStreamId,
  telemetry,
}: Props) {
  const topics = useMemo(() => groupTopics(streams), [streams]);
  const categories = useMemo(
    () => [...new Set(streams.map((stream) => stream.category))].sort(),
    [streams],
  );
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [topicPage, setTopicPage] = useState(() =>
    Math.max(
      0,
      Math.floor(
        topics.findIndex((topic) =>
          topic.readings.some((stream) => stream.id === selectedStreamId),
        ) / TOPICS_PER_PAGE,
      ),
    ),
  );
  const status = useSyncExternalStore(
    telemetry?.subscribeUpdates ?? noSubscription,
    telemetry?.getStatus ?? noSnapshot,
  );
  const showValues = !!telemetry && status?.phase !== "idle";
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return topics
      .map((topic) => ({
        ...topic,
        readings: topic.readings.filter(
          (stream) =>
            (!category || stream.category === category) &&
            (!needle ||
              [
                stream.label,
                stream.topic,
                stream.category,
                stream.payload_pointer,
              ].some((value) => value?.toLowerCase().includes(needle))),
        ),
      }))
      .filter((topic) => topic.readings.length > 0);
  }, [topics, query, category]);
  const filtered = !!query.trim() || !!category;
  const readingCount = matches.reduce(
    (sum, topic) => sum + topic.readings.length,
    0,
  );
  const pages = Math.ceil(matches.length / TOPICS_PER_PAGE);
  const page = Math.min(topicPage, Math.max(0, pages - 1));
  const start = page * TOPICS_PER_PAGE;
  return (
    <section className="sp-topic-browser" aria-label="MQTT topics and readings">
      <h3>
        MQTT topics{" "}
        <small>
          {count(topics.length, "topic")} · {count(streams.length, "reading")}
        </small>
      </h3>
      <p className="sp-topic-intro">
        One topic can carry several readings. Select a reading to inspect it.
      </p>
      <label className="sp-topic-search">
        <Search size={13} />
        <input
          type="search"
          aria-label="Search topics and readings"
          placeholder="Find a topic or reading…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setTopicPage(0);
          }}
        />
      </label>
      <label className="sp-topic-category">
        Category
        <select
          aria-label="Filter topics by category"
          value={category}
          onChange={(event) => {
            setCategory(event.target.value);
            setTopicPage(0);
          }}
        >
          <option value="">All categories</option>
          {categories.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      {filtered && (
        <div className="sp-topic-match-count" role="status">
          {count(matches.length, "matching topic")} ·{" "}
          {count(readingCount, "reading")}
          <button
            onClick={() => {
              setQuery("");
              setCategory("");
              setTopicPage(0);
            }}
          >
            Clear filters
          </button>
        </div>
      )}
      <div className="sp-topic-list">
        {matches.slice(start, start + TOPICS_PER_PAGE).map((topic) => (
          <TopicRow
            key={`${topic.key}:${query}:${category}`}
            topic={topic}
            selectedStreamId={selectedStreamId}
            onSelect={onSelect}
            telemetry={telemetry}
            showValues={showValues}
          />
        ))}
        {!matches.length && (
          <p className="sp-topic-empty">No matching topics or readings.</p>
        )}
      </div>
      {matches.length > TOPICS_PER_PAGE && (
        <div className="sp-topic-pages" aria-label="Topic pages">
          <button
            aria-label="Previous topics"
            disabled={page === 0}
            onClick={() => setTopicPage(page - 1)}
          >
            <ChevronLeft size={13} />
            Previous
          </button>
          <span>
            {start + 1}–{Math.min(start + TOPICS_PER_PAGE, matches.length)} of{" "}
            {matches.length}
          </span>
          <button
            aria-label="Next topics"
            disabled={page === pages - 1}
            onClick={() => setTopicPage(page + 1)}
          >
            Next
            <ChevronRight size={13} />
          </button>
        </div>
      )}
    </section>
  );
}
