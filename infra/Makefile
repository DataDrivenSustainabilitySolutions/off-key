.PHONY: setup check-deploy provision-prod deploy-prod update-labels-prod invite-admin-prod backup-stack-prod restore-stack-prod backup-ambibox-prod
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
	$(UV) run --frozen python -m unittest discover -s tests -v
provision-prod:
	$(ANSIBLE) -i $(INVENTORY) provision.yml $(VAULT) -e release_bootstrap=$(BOOTSTRAP) -e persistence_switch_confirm=$(CONFIRM)
deploy-prod:
	$(ANSIBLE) -i $(INVENTORY) deploy.yml $(VAULT) -e release_bootstrap=$(BOOTSTRAP) -e persistence_switch_confirm=$(CONFIRM)
update-labels-prod:
	$(ANSIBLE) -i $(INVENTORY) update_labels.yml $(VAULT)
invite-admin-prod:
	$(ANSIBLE) -i $(INVENTORY) bootstrap-admin.yml $(VAULT) -e bootstrap_admin_resend=true
backup-stack-prod:
	$(ANSIBLE) -i $(INVENTORY) backup-stack-state.yml $(VAULT)
restore-stack-prod:
	$(ANSIBLE) -i $(INVENTORY) restore-stack-state.yml $(VAULT) $(if $(TS),-e restore_from=$(TS),) -e restore_services=$(SERVICES)
backup-ambibox-prod:
	$(ANSIBLE) -i $(INVENTORY) backup-ambibox-state.yml $(VAULT)
