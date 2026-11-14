.PHONY: check check-infra deploy-prod local-init local-up local-status local-logs local-stop local-bootstrap-admin
REVISION ?= $(shell git rev-parse HEAD)
BOOTSTRAP ?= false
# Erases the database after a backup; set to the stack name (off-key) to confirm.
RESET_DATABASE ?=
# The fast CI suites this branch needs; run before every push (ARGS=--all for all).
ARGS ?=
check:
	python3 dev/check.py $(ARGS)
check-infra:
	$(MAKE) -C infra check-deploy
# Dispatches the Deploy Production workflow; infra/Makefile deploy-prod runs Ansible directly.
deploy-prod:
	gh workflow run deploy-production.yml --ref main -f revision=$(REVISION) -f bootstrap=$(BOOTSTRAP) -f reset_database=$(RESET_DATABASE)

LOCAL_ARGS ?=
local-init:
	python3 dev/local/run.py init $(LOCAL_ARGS)
local-up:
	python3 dev/local/run.py up $(LOCAL_ARGS)
local-status:
	python3 dev/local/run.py status
local-logs:
	python3 dev/local/run.py logs $(LOCAL_ARGS)
local-stop:
	python3 dev/local/run.py stop
local-bootstrap-admin:
	python3 dev/local/run.py bootstrap-admin $(LOCAL_ARGS)
