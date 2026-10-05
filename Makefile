.PHONY: check-infra deploy-prod
REVISION ?= $(shell git rev-parse HEAD)
BOOTSTRAP ?= false
check-infra:
	$(MAKE) -C infra check-deploy
deploy-prod:
	gh workflow run deploy-production.yml --ref main -f revision=$(REVISION) -f bootstrap=$(BOOTSTRAP)
