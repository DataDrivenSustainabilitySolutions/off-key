.PHONY: setup check-deploy provision-prod deploy-prod deploy-demo initialize-demo update-labels-prod invite-admin-prod backup-stack-prod restore-stack-prod backup-broker-route-prod
UV := uv
ANSIBLE := cd ansible && $(UV) run --frozen ansible-playbook
VAULT ?= --ask-vault-pass
INVENTORY ?= inventories/prod/hosts.yml
REVISION ?= latest
BOOTSTRAP ?= false
CONFIRM ?= false
SERVICES ?= postgres,emqx
export ANSIBLE_CONFIG := $(abspath ansible/ansible.cfg)
export OFFKEY_RELEASE_REVISION := $(REVISION)
setup:
	$(UV) sync --frozen
check-deploy:
	$(UV) run --frozen python tests/run_suite.py
provision-prod:
	$(ANSIBLE) -i $(INVENTORY) provision.yml $(VAULT) -e release_bootstrap=$(BOOTSTRAP) -e persistence_switch_confirm=$(CONFIRM)
# Runs Ansible from this machine; the root Makefile deploy-prod dispatches CI instead.
deploy-prod:
	$(ANSIBLE) -i $(INVENTORY) deploy.yml $(VAULT) -e release_bootstrap=$(BOOTSTRAP) -e persistence_switch_confirm=$(CONFIRM)
deploy-demo:
	$(ANSIBLE) -i inventories/demo/hosts.yml deploy.yml $(VAULT) -e release_bootstrap=$(BOOTSTRAP) -e persistence_switch_confirm=$(CONFIRM)
initialize-demo:
	$(ANSIBLE) -i inventories/demo/hosts.yml bootstrap-demo.yml $(VAULT)
update-labels-prod:
	$(ANSIBLE) -i $(INVENTORY) update_labels.yml $(VAULT)
invite-admin-prod:
	$(ANSIBLE) -i $(INVENTORY) bootstrap-admin.yml $(VAULT) -e bootstrap_admin_resend=true
backup-stack-prod:
	$(ANSIBLE) -i $(INVENTORY) backup-stack-state.yml $(VAULT)
restore-stack-prod:
	$(ANSIBLE) -i $(INVENTORY) restore-stack-state.yml $(VAULT) $(if $(TS),-e restore_from=$(TS),) -e restore_services=$(SERVICES)
backup-broker-route-prod:
	$(ANSIBLE) -i $(INVENTORY) backup-broker-route-state.yml $(VAULT)
deploy-observability-prod:
	$(ANSIBLE) -i $(INVENTORY) deploy-observability.yml $(VAULT)
check-observability-prod:
	$(ANSIBLE) -i $(INVENTORY) deploy-observability.yml $(VAULT) -e observability_action=check
pause-observability-prod:
	$(ANSIBLE) -i $(INVENTORY) deploy-observability.yml $(VAULT) -e observability_action=pause
