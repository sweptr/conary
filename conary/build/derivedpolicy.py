#
# Copyright (c) 2007 rPath, Inc.
#
# This program is distributed under the terms of the Common Public License,
# version 1.0. A copy of this license should have been distributed with this
# source file in a file called LICENSE. If it is not present, the license
# is always available at http://www.opensource.org/licenses/cpl.php.
#
# This program is distributed in the hope that it will be useful, but
# without any warranty; without even the implied warranty of merchantability
# or fitness for a particular purpose. See the Common Public License for
# full details.
#

import re, os

from conary import files, trove
from conary.build import buildpackage, filter, packagepolicy, policy

class PackageSpec(policy.Policy):

    bucket = policy.PACKAGE_CREATION

    def preProcess(self):
        # map paths into the correct components
        filters = []
        self.pathObjs = {}
        for trvCs in self.recipe.cs.iterNewTroveList():
            trv = trove.Trove(trvCs)

            if not trv.isCollection():
                regexs = [ re.escape(x[1]) for x in trv.iterFileList() ]
                f = filter.Filter(regexs, self.recipe.macros,
                                  name = trv.getName().split(':')[1])
                filters.append(f)

            for (pathId, path, fileId, version) in trv.iterFileList():
                fileCs = self.recipe.cs.getFileChange(None, fileId)
                self.pathObjs[path] = files.ThawFile(fileCs, pathId)

        pkgFilter = filter.Filter('.*', self.recipe.macros,
                                  name = self.recipe.name)

        self.recipe.autopkg = \
                buildpackage.AutoBuildPackage([ pkgFilter ], filters,
                                              self.recipe)

    def doFile(self, path):
        destdir = self.recipe.macros.destdir

        if path not in self.pathObjs:
            if os.path.isdir(destdir + path):
                return

            # directories get created even if they aren't in any component
            raise builderrors.RecipeFileError(
                    'Cannot add files to derived recipe (%s)' % path)

        self.recipe.autopkg.addFile(path, destdir + path)
        component = self.recipe.autopkg.componentMap[path]
        pkgFile = self.recipe.autopkg.pathMap[path]
        fileObj = self.pathObjs[path]
        pkgFile.inode.owner.set(fileObj.inode.owner())
        pkgFile.inode.group.set(fileObj.inode.group())
        pkgFile.tags.thaw(fileObj.tags.freeze())
        pkgFile.flavor.thaw(fileObj.flavor.freeze())
        pkgFile.flags.thaw(fileObj.flags.freeze())

        component.requiresMap[path] = fileObj.requires()
        component.providesMap[path] = fileObj.provides()

        for comp in self.recipe.autopkg.components.values():
            comp.flavor.union(self.recipe.useFlags)
            comp.requires.union(self.recipe.componentReqs[comp.name])
            comp.provides.union(self.recipe.componentProvs[comp.name])

class Flavor(packagepolicy.Flavor):

    requires = (
        ('PackageSpec', policy.REQUIRED_PRIOR),
    )

    def doFile(self, path):
        componentMap = self.recipe.autopkg.componentMap
        if path not in componentMap:
            return
        pkg = componentMap[path]
        f = pkg.getFile(path)

        if f.flavor().isEmpty():
            Flavor.doFile(self, path)
        else:
            self.packageFlavor.union(f.flavor())

class Requires(packagepolicy.Requires):
    bucket = policy.PACKAGE_CREATION
    requires = (
        ('PackageSpec', policy.REQUIRED_PRIOR),
        ('Provides', policy.REQUIRED_PRIOR),
    )
    filetree = policy.PACKAGE

    def doFile(self, path):
        pkg = self.recipe.autopkg.componentMap[path]
        f = pkg.getFile(path)
        self.whiteOut(path, pkg)
        self.unionDeps(path, pkg, f)

class Provides(packagepolicy.Provides):

    requires = (
        ('PackageSpec', policy.REQUIRED_PRIOR),
        ('Requires', policy.REQUIRED_SUBSEQUENT),
    )

    def doFile(self, path):
        pkg = self.recipe.autopkg.componentMap[path]
        f = pkg.getFile(path)

        m = self.recipe.magic[path]
        macros = self.recipe.macros

        fullpath = macros.destdir + path
        dirpath = os.path.dirname(path)

        self.addExplicitProvides(path, fullpath, pkg, macros, m, f)
        self.addPathDeps(path, dirpath, pkg, f)
        self.unionDeps(path, pkg, f)
