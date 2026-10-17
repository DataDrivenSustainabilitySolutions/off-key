type Publisher = {
  publishAsync(
    topic: string,
    message: string,
    options: { qos: 1 },
  ): Promise<unknown>;
};

/** Publish coherent wall-clock frames at a real sensor cadence, including across calls. */
export async function publishPipelineSamples(
  client: Publisher,
  topics: Record<string, string>,
  count: number,
) {
  for (let index = 0; index < count; index++) {
    const receivedAt = Date.now();
    for (const [at, name] of ["voltage", "current", "temperature"].entries()) {
      const value =
        name === "temperature"
          ? 20 + index / 100
          : (at + 1) * 10 + Math.sin(index / (at + 2));
      await client.publishAsync(
        topics[name]!,
        JSON.stringify({
          payload: JSON.stringify(value),
          received_at: receivedAt,
          upstream_retained: false,
        }),
        { qos: 1 },
      );
    }
    // QoS acknowledgements can finish inside one millisecond on the CI broker.
    // The next frame must represent a later real observation, including the next call.
    await new Promise<void>((resolve) => setTimeout(resolve, 100));
  }
}
