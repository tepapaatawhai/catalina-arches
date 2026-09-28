default: help

TOOLKIT_REPO = https://github.com/flaxandteal/arches-container-toolkit
TOOLKIT_FOLDER = docker
TOOLKIT_RELEASE = main
ARCHES_PROJECT ?= $(shell ls -1 */__init__.py | head -n 1 | sed 's/\/.*//g')
ifeq ($(wildcard /../arches),)
	ARCHES_ROOT=$(realpath ../arches)
else
	
	ARCHES_ROOT=
endif
ifneq ($(ARCHES_ROOT),)
  DOCKER_COMPOSE_FILES = -f docker/docker-compose.yml -f docker/docker-compose.volumes.yml -f docker-compose.redis.yml
else
  DOCKER_COMPOSE_FILES = -f docker/docker-compose.yml -f docker-compose.redis.yml
endif
ARCHES_BASE = ghcr.io/flaxandteal/arches-base:v8.2.0a8-v2
ARCHES_PROJECT_ROOT = $(shell pwd)/
DOCKER_COMPOSE_COMMAND = ARCHES_PROJECT_ROOT=$(ARCHES_PROJECT_ROOT) ARCHES_BASE=$(ARCHES_BASE) ARCHES_PROJECT=$(ARCHES_PROJECT) ARCHES_ROOT=$(ARCHES_ROOT) docker compose -p $(ARCHES_PROJECT) $(DOCKER_COMPOSE_FILES)
CMD ?=

.PHONY: cypress test docker rebuild-images build create-github-action down run web npm-development docker-compose manage webpack clean help npm-install npm-update create-apps-dir update-urls-debug install-app

create: docker
	echo $(shell id -u)
	FORUSER=$(shell id -u) $(DOCKER_COMPOSE_COMMAND) run -e FORUSER=$(shell id -u) --entrypoint /bin/sh arches_base -c ". ../ENV/bin/activate; apt install -y git; pip install 'pyjwt<2.1,>=2.0.0' 'cryptography<3.4.0' --only-binary cryptography --only-binary cffi; cd /local_root; ls -ltr; id -u; arches-admin startproject $(ARCHES_PROJECT) && mv docker Makefile $(ARCHES_PROJECT); ls -ltr; echo \$${FORUSER}; groupadd -g \$${FORUSER} externaluser; useradd -u \$${FORUSER} -g \$${FORUSER} externaluser; chown -R \$${FORUSER}:\$${FORUSER} $(ARCHES_PROJECT); echo \$$?; ls -ltr $(ARCHES_PROJECT)"

cypress.config.js: dl-docker
	cp docker/tests/cypress.config.js $(ARCHES_PROJECT_ROOT)
	cp -R docker/tests/cypress $(ARCHES_PROJECT_ROOT)

cypress: cypress.config.js

test: cypress

docker: dl-docker

create-apps-dir:
	@if [ ! -d "../arches_apps" ]; then \
    	mkdir -p "../arches_apps"; \
		APPS_DIR=../arches_apps \
    	echo "Created arches_apps directory"; \
	else \
    	echo "arches_apps already exists"; \
	fi

install-app:
	@if [ -z "$(URL)" ]; then \
		echo "Error: No GitHub URL provided. Usage: make install-app URL=<repo_url>"; \
		exit 1; \
	fi
	python3 $(TOOLKIT_FOLDER)/install_app.py "$(URL)" --project-root "$(ARCHES_PROJECT_ROOT)"
	@echo ""
	@echo "You may need to run python manage.py migrate to install any models in the app"
	@echo "Make sure to rebuild the project frontend"

update-urls-debug:
	@if ! grep -q "from django.contrib.staticfiles import views" $(ARCHES_PROJECT_ROOT)/$(ARCHES_PROJECT)/urls.py; then \
    	echo "Adding DEBUG static file serving to urls.py"; \
    	echo "\nif settings.DEBUG:\n    from django.contrib.staticfiles import views\n    from django.urls import re_path\n    urlpatterns += [\n        re_path(r'^static/(?P<path>.*)$$', views.serve),\n    ]" >> $(ARCHES_PROJECT_ROOT)/$(ARCHES_PROJECT)/urls.py; \
	else \
    	echo "DEBUG static file serving already exists in urls.py"; \
	fi

dl-docker:
	@echo ARCHES_PROJECT is [$(ARCHES_PROJECT)]
	@echo $(wildcard $(TOOLKIT_FOLDER)/CONTAINER_TOOLS)
ifneq ("$(wildcard init-unix.sql)","")
	$(error It looks like you are running make in the tools directory itself - run 'make help' for information. Exiting:)
# else ifeq ("$(wildcard manage.py)","")
# 	$(error It looks like you are not running make in the top-level project folder (where manage.py lives) - run 'make help' for information. Exiting:)
else ifneq ("$(wildcard $(TOOLKIT_FOLDER))","")
ifneq ("$(wildcard $(TOOLKIT_FOLDER)/CONTAINER_TOOLS)","")
	$(error It looks like your ./$(TOOLKIT_FOLDER) subfolder does not contain the Arches F&T Container Toolkit\
		you can try changing TOOLKIT_FOLDER in the Makefile to avoid a clash, but this is not a fully-supported use-case.)
endif
	@# It looks like the container tools are in place, so carry on.
else
	@echo "Did not find the Arches F&T Container Toolkit"
ifneq ("$(shell grep container-toolkit .gitmodules 2>/dev/null)","")
	@echo "Submodule present so updating it"
	git submodule update --init
endif
ifeq ("$(shell (which git > /dev/null) && git rev-parse --is-inside-work-tree 2>/dev/null)", "true")
	@echo Fetching as a git submodule
	git submodule add --force $(TOOLKIT_REPO) $(TOOLKIT_FOLDER)
else
	@echo No git or not a repo -- fetching as a tarball
	mkdir -p $(TOOLKIT_FOLDER)
	wget -q --content-disposition $(TOOLKIT_REPO)/tarball/$(TOOLKIT_RELEASE) -O $(TOOLKIT_FOLDER)/_toolkit.tgz
	@echo `export TD=$$(tar -vtzf $(TOOLKIT_FOLDER)/_toolkit.tgz --exclude='*/*' | awk '{print $$NF}' | head -n 1); tar -xzf $(TOOLKIT_FOLDER)/_toolkit.tgz; rm -rf $(TOOLKIT_FOLDER); echo Moving $$TD to $(TOOLKIT_FOLDER); mv $$TD $(TOOLKIT_FOLDER)`
endif
	@echo "Arches F&T Container Toolkit now in [$(TOOLKIT_FOLDER)]"
endif
	@if [ "$$(diff Makefile $(TOOLKIT_FOLDER)/Makefile)" != "" ]; then echo "Your Makefile in this directory does not match the one in directory [$(TOOLKIT_FOLDER)], do you need to update it by copying it over this one or vice versa?"; echo; fi

rebuild-images: docker
	$(DOCKER_COMPOSE_COMMAND) build

npm-install: docker
	$(DOCKER_COMPOSE_COMMAND) run --entrypoint /web_root/entrypoint.sh arches_worker install_npm_components

npm-update: docker
	$(DOCKER_COMPOSE_COMMAND) run --entrypoint /web_root/entrypoint.sh arches_worker update_npm_components

build: docker
	# We need to have certain node modules, so if the additional ones are missing, clean the folder to ensure boostrap does so.
	if [ -z node_modules/jquery-validation ]; then rm -rf node_modules; fi
	$(DOCKER_COMPOSE_COMMAND) stop
	$(DOCKER_COMPOSE_COMMAND) run --entrypoint /web_root/entrypoint.sh arches_worker install_npm_components
	$(DOCKER_COMPOSE_COMMAND) run --entrypoint /web_root/entrypoint.sh arches_worker bootstrap

	if [ -d $(ARCHES_PROJECT)/pkg ]; then $(TOOLKIT_FOLDER)/act.py . load_package --yes; fi
	$(DOCKER_COMPOSE_COMMAND) run --entrypoint /web_root/entrypoint.sh arches_worker run_npm_build_development
	$(DOCKER_COMPOSE_COMMAND) stop
	$(MAKE) create-apps-dir
	$(MAKE) update-urls-debug

create-github-action: cypress docker
	mkdir -p  $(ARCHES_PROJECT_ROOT).github/workflows
	cp $(TOOLKIT_FOLDER)/project.yml $(ARCHES_PROJECT_ROOT).github/workflows
	sed -i "s/__ARCHESPROJECT__/$(ARCHES_PROJECT)/g" $(ARCHES_PROJECT_ROOT).github/workflows/project.yml
	sed -i "s#__ARCHESBASE__#$(ARCHES_BASE)#g" $(ARCHES_PROJECT_ROOT).github/workflows/project.yml
	@echo "You will now need to git-add your .github folder and commit it. On your next push, you should find Arches builds."

down: docker
	$(DOCKER_COMPOSE_COMMAND) down

run: docker
	$(DOCKER_COMPOSE_COMMAND) up

web: docker
	$(DOCKER_COMPOSE_COMMAND) stop arches
	$(DOCKER_COMPOSE_COMMAND) run --service-ports arches

npm-development: docker
	$(DOCKER_COMPOSE_COMMAND) run --entrypoint /web_root/entrypoint.sh arches_worker run_npm_build_development

docker-compose: docker
	$(DOCKER_COMPOSE_COMMAND) $(shell echo $(CMD))

manage: docker
	$(DOCKER_COMPOSE_COMMAND) run --entrypoint /bin/bash arches_worker -c '. ../ENV/bin/activate; python manage.py $(CMD)'

webpack: docker
	$(DOCKER_COMPOSE_COMMAND) run --entrypoint /web_root/entrypoint.sh arches_worker run_npm_build_development

clean: docker
	@echo -n "This will remove all database and elasticsearch data, are you sure? [y/N] " && read confirmation && [ $${confirmation:-N} = y ]
	$(DOCKER_COMPOSE_COMMAND) down -v --rmi all

help:
	@echo
	@echo "ARCHES F&T CONTAINER TOOLS"
	@echo "=========================="
	@echo
	@echo "This Makefile should be present in the top level directory of an Arches project, where manage.py lives. We make some"
	@echo "assumptions based on standard Arches project layout, as set up by 'arches-project create'. Running any other make"
	@echo "command should check whether there is a ./docker/ subfolder, and if not attempt to add the container tools as a submodule"
	@echo "if your project it versioned in git, or download a released copy to ./docker/ if not."
	@echo
	@echo "These are not directly compatible with the container approach in the Arches core tree (although we would like to align"
	@echo "progressively). If you are considering using these, take a look at ./docker/README.md."
	@echo
	@echo \(== ARCHES_PROJECT is [$(ARCHES_PROJECT)] ==\)
	@echo
	@echo "To set up a new project, ensure the ARCHES_PROJECT above is correct, then run 'make build', followed by 'make run'."
	@echo "If you do not see a project above or it is wrong, ensure that there is exactly one subfolder of this directory with an"
	@echo "__init__.py file."
	@echo
	@echo "Note that '$(ARCHES_PROJECT)/urls.py' must have (manually added):"
	@echo "	if settings.DEBUG:"
	@echo "	    from django.contrib.staticfiles import views"
	@echo "	    from django.urls import re_path"
	@echo "	    urlpatterns += ["
	@echo "		re_path(r'^static/(?P<path>.*)$$', views.serve),"
	@echo "	    ]"
	@echo
	@echo "To run general docker-compose commands, use:"
	@echo "  make docker-compose CMD='...'"
	@echo "or:"
	@echo "  ARCHES_PROJECT_ROOT=$(ARCHES_PROJECT_ROOT) ARCHES_BASE=$(ARCHES_BASE) ARCHES_PROJECT=$(ARCHES_PROJECT) docker-compose -p $(ARCHES_PROJECT) -f docker/docker-compose.yml ..."
	@echo
	@echo "For example:"
	@echo "  make docker-compose CMD='version'"
