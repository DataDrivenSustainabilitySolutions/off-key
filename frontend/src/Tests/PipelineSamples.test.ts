import { expect, it, vi } from "vitest";
import { publishPipelineSamples } from "../../e2e/helpers/pipelineSamples";


it("publishes coherent real-time frames without duplicate observation timestamps, even across batches and immediate acknowledgements", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-16T12:00:00Z"));
  const messages: Array<{
    topic: string;
    receivedAt: number;
    sentAt: number;
    qos: number;
  }> = [];
  const client = {
    publishAsync: vi.fn(
      async (topic: string, body: string, options: { qos: 1 }) => {
        const envelope = JSON.parse(body) as { received_at: number };
        messages.push({
          topic,
          receivedAt: envelope.received_at,
          sentAt: Date.now(),
          qos: options.qos,
        });
      },
    ),
  };
  const topics = {
    voltage: "voltage",
    current: "current",
    temperature: "temperature",
  };
  const first = publishPipelineSamples(client, topics, 2);
  await vi.advanceTimersByTimeAsync(200);
  await first;
  const second = publishPipelineSamples(client, topics, 1);
  await vi.advanceTimersByTimeAsync(100);
  await second;

  expect(messages).toHaveLength(9);
  const timestamps: number[] = [];
  for (let offset = 0; offset < messages.length; offset += 3) {
    const frame = messages.slice(offset, offset + 3);
    const timestamp = frame[0]!.receivedAt;
    expect(frame.map((message) => message.topic)).toEqual(
      Object.values(topics),
    );
    expect(new Set(frame.map((message) => message.receivedAt)).size).toBe(1);
    expect(timestamp).toBe(frame[0]!.sentAt);
    for (const message of frame) {
      expect(message.receivedAt).toBeLessThanOrEqual(message.sentAt);
      expect(message.qos).toBe(1);
    }
    if (timestamps.length)
      expect(timestamp - timestamps[timestamps.length - 1]!).toBeGreaterThanOrEqual(100);
    timestamps.push(timestamp);
  }
  expect(new Set(timestamps).size).toBe(3);
});
