#
# Copyright (c) SAS Institute Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


SUBDIRS=arch recipeTemplates use site mirrors components

dist_files = Makefile pubring.gpg trustdb.gpg macros

all: default-subdirs

install: install-subdirs
	$(INSTALL) --mode=644 pubring.gpg trustdb.gpg macros $(DESTDIR)/etc/conary

dist: default-dist

clean: default-clean

include ../Make.rules
