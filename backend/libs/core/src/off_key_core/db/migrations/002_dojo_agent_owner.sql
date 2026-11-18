-- A dataset or run made with an agent's key names that agent, so the key can
-- delete its own test copies and replays and nothing else. Runs already kept
-- the agent's name; a run whose agent still holds that name is its own again.
ALTER TABLE dojo_datasets ADD COLUMN IF NOT EXISTS created_by_agent text;
ALTER TABLE dojo_datasets ADD COLUMN IF NOT EXISTS created_by_agent_id integer;
ALTER TABLE dojo_runs ADD COLUMN IF NOT EXISTS created_by_agent_id integer;
UPDATE dojo_runs
SET created_by_agent_id = agents.id
FROM agents
WHERE dojo_runs.created_by_agent_id IS NULL
  AND lower(agents.name) = lower(dojo_runs.config ->> 'created_by_agent');
