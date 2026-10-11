.PHONY: check-infra deploy-prod local-init local-up local-status local-logs local-stop local-bootstrap-admin
REVISION ?= $(shell git rev-parse HEAD)
BOOTSTRAP ?= false
check-infra:
	$(MAKE) -C infra check-deploy
deploy-prod:
	gh workflow run deploy-production.yml --ref main -f revision=$(REVISION) -f bootstrap=$(BOOTSTRAP)

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
