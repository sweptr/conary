#
# Copyright (c) rPath, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#


import os, tempfile, sys

from conary import errors, files, trove
from conary.lib import digestlib, util
from conary.local import journal
from conary.repository import changeset

class CapsuleOperation(object):

    def __init__(self, root, db, changeSet, callback, fsJob,
                 skipCapsuleOps = False):
        self.root = root
        self.db = db
        self.changeSet = changeSet
        self.fsJob = fsJob
        self.callback = callback
        self.errors = []
        self.skipCapsuleOps = skipCapsuleOps

    def apply(self, fileDict, justDatabase = False, noScripts = False):
        raise NotImplementedError

    def install(self, troveCs):
        raise NotImplementedError

    def remove(self, trove):
        raise NotImplementedError

    def getErrors(self):
        return self.errors

    def _error(self, e):
        self.errors.append(e)

class ConaryOwnedJournal(journal.JobJournal):

    # keep track of files which conary wants to own despite them being
    # in the underlying capsule; we back those up before the capsule
    # handler runs, and then restore them. this effectively takes ownership
    # of those files away from the underlying packaging tool

    def __init__(self, root = '/'):
        tmpfd, tmpname = tempfile.mkstemp()
        journal.JobJournal.__init__(self, tmpname, root = root, create = True)
        os.close(tmpfd)
        os.unlink(tmpname)

class SingleCapsuleOperation(CapsuleOperation):

    def __init__(self, *args, **kwargs):
        CapsuleOperation.__init__(self, *args, **kwargs)
        self.installs = []
        self.removes = []
        self.preserveSet = set()

    def _filesNeeded(self):
        return [ x[1] for x in self.installs ]

    def preservePath(self, path):
        self.preserveSet.add(path)

    def doApply(self, justDatabase = False, noScripts = False):
        raise NotImplementedError

    def apply(self, fileDict, justDatabase = False, noScripts = False):
        if not justDatabase and self.preserveSet:
            capsuleJournal = ConaryOwnedJournal(self.root)
            for path in self.preserveSet:
                fullPath = self.root + path
                capsuleJournal.backup(fullPath, skipDirs = True)
                if not util.removeIfExists(fullPath):
                    capsuleJournal.create(fullPath)
        else:
            capsuleJournal = None

        try:
            self.doApply(fileDict, justDatabase = justDatabase, noScripts = noScripts)
        finally:
            if capsuleJournal:
                capsuleJournal.revert()

    def install(self, flags, troveCs):
        if troveCs.getOldVersion():
            oldTrv = self.db.getTrove(*troveCs.getOldNameVersionFlavor())
            trv = oldTrv.copy()
            trv.applyChangeSet(troveCs)
        else:
            oldTrv = None
            trv = trove.Trove(troveCs)

        #if oldTrv and oldTrv.troveInfo.capsule == trv.troveInfo.capsule:
            # the capsule hasn't changed, so don't reinstall it
            #return None

        for pathId, path, fileId, version in trv.iterFileList(capsules = True):
            # there should only be one...
            break

        assert(pathId == trove.CAPSULE_PATHID)

        if oldTrv:
            for oldPathId, oldPath, oldFileId, oldVersion in \
                            oldTrv.iterFileList(capsules = True):
                # there should only be one...
                break

            assert(oldPathId == trove.CAPSULE_PATHID)
            if (oldFileId == fileId or
                    oldTrv.troveInfo.capsule == trv.troveInfo.capsule):
                # good enough. this means changing capsule information
                # in trove info won't fool us into trying to reinstall
                # capsules which haven't changed. we check the capsule
                # information as well because derived packages change
                # the capsule fileIds. ugh.
                #
                # we do it in this order to make sure the test suite tests
                # both sides of the "or" above
                return

            self.remove(oldTrv)

        # is the capsule new or changed?
        changedFileInfos = [ x for x in troveCs.getChangedFileList()
                                if x[0] == trove.CAPSULE_PATHID ]
        if changedFileInfos:
            oldFileId = oldTrv.getFile(pathId)[1]
            oldFileObjs = self.db.getFileStream(oldFileId)
            fileObj = files.ThawFile(oldFileObjs, pathId)
            fileChange = self.changeSet.getFileChange(oldFileId, fileId)
            fileObj.twm(fileChange, fileObj)
            sha1 = fileObj.contents.sha1()
        else:
            fileStream = self.changeSet.getFileChange(None, fileId)
            sha1 = files.frozenFileContentInfo(fileStream).sha1()

        self.installs.append((troveCs, (pathId, path, fileId, sha1)))
        return (oldTrv, trv)

    def remove(self, trv):
        self.removes.append(trv)

class MetaCapsuleOperations(CapsuleOperation):

    availableClasses = { 'rpm' : ('conary.local.rpmcapsule',
                                  'RpmCapsuleOperation') }

    def __init__(self, root = '/', *args, **kwargs):
        CapsuleOperation.__init__(self, root, *args, **kwargs)
        self.capsuleClasses = {}

    def apply(self, justDatabase = False, noScripts = False,
              capsuleChangeSet = None):
        if capsuleChangeSet:
            # Previous jobs will have moved the pointer in the auxilliary
            # changeset, so reset it at the start of each job.
            capsuleChangeSet.reset()
        tmpDir = os.path.join(self.root, 'var/tmp')
        if not os.path.isdir(tmpDir):
            # For empty roots or roots that are not systems (e.g. source
            # checkouts), just put capsules in the root directory.
            tmpDir = self.root
        fileDict = {}
        for kind, obj in sorted(self.capsuleClasses.items()):
            fileDict.update(
                dict(((x[0], x[2], x[3]), x[1]) for x in obj._filesNeeded()))

        try:
            for ((pathId, fileId, sha1), path) in sorted(fileDict.items()):
                tmpfd, tmpname = tempfile.mkstemp(dir=tmpDir, prefix=path,
                        suffix='.conary')
                fType, fContents = self.changeSet.getFileContents(pathId,
                                                                  fileId)
                if (fType == changeset.ChangedFileTypes.hldr):
                    if (capsuleChangeSet):
                        try:
                            result = capsuleChangeSet.getFileContents(pathId,
                                                                      fileId)
                            fObj = result[1].get()
                        except KeyError:
                            raise errors.MissingRollbackCapsule('Cannot find '
                                'RPM %s to perform local rollback' % path)

                else:
                    fObj = fContents.get()

                d = digestlib.sha1()
                util.copyfileobj(fObj, os.fdopen(tmpfd, "w"), digest = d)
                actualSha1 = d.digest()
                if actualSha1 != sha1:
                    raise files.Sha1Exception(path)

                # tmpfd is closed when the file object created by os.fdopen
                # disappears
                fileDict[(pathId, fileId)] = tmpname

            for kind, obj in sorted(self.capsuleClasses.items()):
                obj.apply(fileDict, justDatabase = justDatabase, noScripts = noScripts)
        finally:
            for tmpPath in fileDict.values():
                try:
                    os.unlink(tmpPath)
                except:
                    pass

    @classmethod
    def preload(cls, kinds):
        for kind in kinds:
            modName, className = cls.availableClasses[kind]
            if modName not in sys.modules:
                __import__(modName)

    def getCapsule(self, kind):
        if kind not in self.capsuleClasses:
            module, klass = self.availableClasses[kind]

            if module not in sys.modules:
                __import__(module)
            self.capsuleClasses[kind] = \
                getattr(sys.modules[module], klass)(self.root, self.db,
                                                    self.changeSet,
                                                    self.callback,
                                                    self.fsJob)

        return self.capsuleClasses[kind]

    def install(self, flags, troveCs):
        absTroveInfo = troveCs.getFrozenTroveInfo()
        capsuleInfo = trove.TroveInfo.find(trove._TROVEINFO_TAG_CAPSULE,
                                             absTroveInfo)
        if not capsuleInfo or not capsuleInfo.type():
            return False

        if (troveCs.getOldVersion() and troveCs.getOldVersion().onLocalLabel()):
            # diff between a capsule and local label is represented
            # as a conary
            return False

        if self.skipCapsuleOps:
            return True

        capsule = self.getCapsule(capsuleInfo.type())
        capsule.install(flags, troveCs)

        return True

    def remove(self, trove):
        cType = trove.troveInfo.capsule.type()
        if not cType:
            return False

        if self.skipCapsuleOps:
            return True

        capsule = self.getCapsule(cType)
        capsule.remove(trove)
        return True

    def getErrors(self):
        e = []
        for capsule in self.capsuleClasses.values():
            e += capsule.getErrors()

        return e
