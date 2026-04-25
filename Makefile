SHELL := /bin/bash

.PHONY: bootstrap lock smoke-c00 smoke-c01 smoke-c04 smoke-c05 smoke-c06 smoke-c07

bootstrap:
	bash scripts/bootstrap.sh

lock:
	bash scripts/compile_requirements_lock.sh

smoke-c00:
	bash scripts/verify_c00.sh

smoke-c01:
	bash scripts/verify_c01.sh

smoke-c04:
	bash scripts/verify_c04.sh

smoke-c05:
	bash scripts/verify_c05.sh

smoke-c06:
	bash scripts/verify_c06.sh

smoke-c07:
	bash scripts/verify_c07.sh
