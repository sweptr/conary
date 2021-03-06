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


import logging
import os
from conary.lib import log as cny_log
from conary.server import wsgi_hooks

log = logging.getLogger(__name__)


def _getVhostDir(environ):
    if 'CONARY_VHOST_DIR' in os.environ:
        vhostDir = os.environ['CONARY_VHOST_DIR']
    elif 'CONARY_VHOST_DIR' in environ:
        vhostDir = environ['CONARY_VHOST_DIR']
    else:
        return None
    if not os.path.isdir(vhostDir):
        return None
    return vhostDir


def application(environ, start_response):
    if not logging.root.handlers:
        cny_log.setupLogging(consoleLevel=logging.INFO, consoleFormat='apache',
                consoleStream=environ['wsgi.errors'])

    vhostDir = _getVhostDir(environ)
    if not vhostDir:
        log.error("The CONARY_VHOST_DIR environment variable must be set to "
                "an existing directory")
        start_response('500 Internal Server Error',
                [('Content-Type', 'text/plain')])
        return ["ERROR: The server is not configured correctly. Check the "
            "server's error logs.\r\n"]

    pathhost = httphost = repohost = None
    if environ.get('HTTP_X_CONARY_VHOST'):
        pathhost = environ['HTTP_X_CONARY_VHOST']
    elif environ.get('PATH_INFO'):
        path = environ['PATH_INFO'].split('/')
        if path[0] == '' and '.' in path[1]:
            # http://big.server/foo.com/conary/browse
            pathhost = path[1]
            environ['SCRIPT_NAME'] += '/'.join(path[:2])
            environ['PATH_INFO'] = '/' + '/'.join(path[2:])
    if not pathhost:
        # http://repo.hostname/conary/browse
        httphost = environ.get('HTTP_HOST', '').split(':')[0]
        if not httphost:
            start_response('400 Bad Request', [('Content-Type', 'text/plain')])
            return ["ERROR: No server name was supplied\r\n"]
        # repositoryMap repo.hostname http://big.server/conary/
        repohost = environ.get('HTTP_X_CONARY_SERVERNAME', '')
    names = [x for x in [pathhost, httphost, repohost] if x]
    for var in names:
        if '..' in var or '/' in var or os.path.sep in var:
            start_response('400 Bad Request', [('Content-Type', 'text/plain')])
            return ["ERROR: Illegal header value\r\n"]
        if var:
            path = os.path.join(vhostDir, var)
            if os.path.isfile(path):
                break
    else:
        log.error("vhost path %s not found", path)
        start_response('404 Not Found', [('Content-Type', 'text/plain')])
        names = ' or '.join(names)
        return ["ERROR: No server named %s exists here\r\n" % names]
    environ['conary.netrepos.config_file'] = path
    return wsgi_hooks.makeApp({})(environ, start_response)
