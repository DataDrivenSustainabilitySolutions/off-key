# Turn on automatic production releases

Think of GitHub as a robot holding a locked toolbox. A merged change is its work
order; the tests are its checklist; production secrets are the tools. The repository
can stay public because the toolbox is stored in a protected GitHub environment.
Code running with those tools is trusted, so protect changes to deployment code.

## 1. Prepare the branch

Review the integration branch, then push it and open a pull request when ready.
Ordinary checks use synthetic configuration and should pass before any live setup.
Do not merge failing checks. Missing production secrets prevent a live deployment,
not pull request testing. Keep the old private infrastructure checkout and its
private recovery files while completing the cutover.

## 2. Create the production environment

In **off-key → Settings → Environments**, create **production**.
Select deployment branches and allow **main only**. Leave required reviewers off
for the agreed automatic deployment model. Under environment variables add
`AUTO_DEPLOY_ENABLED` with value `false`. This is the off switch; automatic releases
stay disabled until the first manual release succeeds.

## 3. Give the robot its private toolbox

Under that environment's **Secrets**, create these exact names:

| Secret | What to paste |
| --- | --- |
| `OFFKEY_PROD_VAULT` | The complete existing **encrypted** production `vault.yml`, starting with `$ANSIBLE_VAULT;`. Paste raw text, without base64. |
| `OFFKEY_VAULT_PASSWORD` | The password that unlocks that vault. |
| `OFFKEY_PROD_INVENTORY` | A portable production `hosts.yml`, based on the example in `infra/ansible/inventories/prod/`. |
| `OFFKEY_DEPLOY_SSH_KEY` | A dedicated deployment private SSH key. |
| `OFFKEY_DEPLOY_KNOWN_HOSTS` | Verified SSH host keys for every inventory address and port. |
| `TS_OAUTH_CLIENT_ID` | The management Tailscale federated identity client ID from step 5. |
| `TS_AUDIENCE` | Its audience from step 5. |

The inventory names must match **docker node ls**. Use management-tailnet addresses
for the manager and workers, their existing SSH ports and their deployment users.
Remove laptop-specific `ansible_ssh_private_key_file`, `ProxyCommand`, `ProxyJump`
and `UserKnownHostsFile` settings. The workflow supplies its own key and verified
host list. Worker SSH forwarding on port 2222 remains necessary where currently
used; the retired Windows guide is unnecessary for a GitHub runner.

GitHub limits each secret to 48 KiB. The existing encrypted vault fits; base64 would
unnecessarily enlarge it. If it grows past the limit, split it into reviewed smaller
secrets and adjust materialization before enabling releases. Keep the encrypted vault
and password in your independent password manager/recovery storage too: GitHub is
not a system for downloading secrets back to a new laptop.

The workflow uses its temporary `GITHUB_TOKEN` for GHCR; it does not need a new PAT.
For existing private packages, check **Package settings → Manage Actions access**
and grant **off-key** read access. Keep the existing vault registry credential only
for direct local recovery until you deliberately replace it.

## 4. Authorize SSH and verify the locks on the servers

Generate a dedicated Ed25519 key, for example with `ssh-keygen -t ed25519 -f
~/.ssh/offkey-deploy`. Store the private key in the environment secret. Add its
public key to each existing deployment user's `authorized_keys`. These users need
Docker access and the existing noninteractive sudo privileges used by Ansible.
Keep your personal recovery key; remove neither working access nor vendor identity.

Obtain each server's Ed25519 host fingerprint from its trusted console or an already
verified SSH session. Use `infra/scripts/trust_ssh_host.py` to enroll that exact
fingerprint into a separate known-hosts file, then upload that file as the secret.
A bare `ssh-keyscan` is insufficient verification. Nondefault SSH ports use
`[address]:2222` entries. The CI connection enforces host-key checking.

## 5. Let the robot reach the servers through Tailscale

In the **management** tailnet, create `tag:offkey-ci`. Create a federated identity
using GitHub's OIDC issuer `https://token.actions.githubusercontent.com`, the
`auth_keys` scope, and permission to create ephemeral devices with that tag.
Restrict trust to this repository's **production** environment and the deployment
workflow on **main**. Use GitHub's numeric repository/owner IDs as additional
immutable claims where supported. Copy the client ID and audience into step 3.

A GitHub environment changes the default subject to
`repo:DataDrivenSustainabilitySolutions/off-key:environment:production`.
Also constrain the repository, `ref` (`refs/heads/main`) and `workflow_ref`
(`DataDrivenSustainabilitySolutions/off-key/.github/workflows/deploy-production.yml@refs/heads/main`)
claims in the federated identity. Do not configure trust for every repository or PR.

Give that tag ordinary network access to **only** the actual deployment addresses:
manager TCP 22 and worker TCP 2222 (adjust to the real inventory). For example,
merge this into your existing policy using your real destination addresses:

```json
{
  "tagOwners": {"tag:offkey-ci": ["autogroup:admin"]},
  "grants": [
    {"src": ["tag:offkey-ci"], "dst": ["100.100.10.1"], "ip": ["tcp:22"]},
    {"src": ["tag:offkey-ci"], "dst": ["100.100.10.2", "100.100.10.3"], "ip": ["tcp:2222"]}
  ]
}
```

This uses the existing OpenSSH service; it does not require Tailscale SSH rules.
The runner leaves the tailnet after its job. Do not enroll it into the separate
vendor tailnet or give it vendor identity, NFS, database or MQTT network access.
Review broader existing tailnet grants too; a narrow new rule cannot undo an
existing allow-all rule.

## 6. Keep main protected

In **Settings → Rules → Rulesets**, or the existing branch protection rule, require
the existing review policy and code-owner review for infrastructure/workflows/SQL.
The new CODEOWNERS file names the existing owner. Preserve the current owner and
administrator policy while adding these required checks after they have appeared:

- `pre-commit (3.12)` and `pre-commit (3.14)`
- `frontend`
- `deployment-smoke`
- `collection (5.8.7)` and `collection (6.3.1)`
- `infrastructure`
- the existing Docker Validate checks (select their exact displayed names)

Docker Publish runs after a main push, so it is a release gate rather than a PR
merge check. Even an administrator merge cannot bypass the deployment workflow's
same-commit success checks. Do not require Deploy Production as a pre-merge check.

## 7. Merge, then do the first controlled release

After the PR is green and reviewed, merge it. Wait for **all five** main workflows:
CI, Deployment Smoke, MQTT Collection Integration, Infrastructure Validation and
Docker Publish. Under **Actions → Deploy Production → Run workflow**, select
**main**, paste its complete 40-character commit SHA, and check **bootstrap**.

Choose a quiet maintenance window. The robot stops old writers, validates a private
database backup on the database server, upgrades the schema, captures existing
monitor settings, stops their old workers, deploys the exact images and restarts the
monitors with fresh calibration. Original telemetry and evidence stay in the database.

Watch the workflow result, then check the website, login, Data sources and monitor
status yourself. Quiet chargers may show waiting for data. On the manager,
`/opt/stacks/off-key/release.json` must name this commit, and
`release-maintenance.json` must be gone. The runtime database operation must be
complete. A failure leaves the last verified release unchanged; use the recovery
runbook and retry the same SHA before attempting another release.

## 8. Flip the switch

Only after step 7 succeeds, change `AUTO_DEPLOY_ENABLED` to `true` in the production
environment. Future runtime changes merged into main deploy automatically after all
release checks pass. Documentation changes skip deployment; the comparison starts
at the last verified release, so an earlier runtime change cannot be skipped.

After this cutover is verified and your independent recovery material is safe,
archive the old private **off-key-infra** repository. Its history and private
university/vendor notes stay private; they are not imported into public Git history.

For another laptop, clone off-key and use `make deploy-prod REVISION=<tested SHA>`
to dispatch GitHub. No local production environment files are needed for normal CD.
Changing live configuration means updating the encrypted vault/inventory environment
secrets and manually dispatching a tested release; secret edits alone do not trigger CD.

References: [GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[workflow_run semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run),
[Tailscale GitHub Action](https://tailscale.com/docs/integrations/github/github-action),
[workload identity federation](https://tailscale.com/docs/features/workload-identity-federation).
