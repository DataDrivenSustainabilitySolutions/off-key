// GitHub supplies cache runtime credentials to JavaScript actions, not shell
// steps. Keep them in this child process; do not persist them to GITHUB_ENV.
const { spawnSync } = require("node:child_process");

const result = spawnSync(
  "/bin/bash",
  ["--noprofile", "--norc", "-e", "-o", "pipefail", "-c", process.env.INPUT_RUN],
  { stdio: "inherit", env: { ...process.env, ABERRATION_BUILD_CACHE: "1" } },
);
if (result.error) throw result.error;
process.exit(result.status ?? 1);
