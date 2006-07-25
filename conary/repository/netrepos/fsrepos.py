#
# Copyright (c) 2004-2006 rPath, Inc.
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

# implements a db-based repository

import errno
import traceback
import sys

from conary import files, trove
from conary.deps import deps
from conary.lib import util, openpgpfile, sha1helper
from conary.repository import changeset, errors, filecontents
from conary.repository.datastore import DataStoreRepository, DataStore
from conary.repository.datastore import DataStoreSet
from conary.lib.openpgpfile import TRUST_FULL, TRUST_UNTRUSTED
from conary.repository.repository import AbstractRepository
from conary.repository.repository import ChangeSetJob
from conary.repository import netclient

class FilesystemChangeSetJob(ChangeSetJob):
    def __init__(self, *args, **kw):
        self.mirror = kw.pop('mirror', False)
        ChangeSetJob.__init__(self, *args, **kw)

    def markTroveRemoved(self, name, version, flavor):
        self.repos.markTroveRemoved(name, version, flavor)

    def checkTroveCompleteness(self, trv):
        if not self.mirror and not trv.troveInfo.sigs.sha1():
            raise errors.TroveChecksumMissing(trv.getName(), trv.getVersion(),
                                              trv.getFlavor())
        if trv.troveInfo.incomplete():
            if trv.troveInfo.troveVersion() > trove.TROVE_VERSION:
                raise errors.TroveSchemaError(trv.getName(), trv.getVersion(),
                                              trv.getFlavor(),
                                              trv.troveInfo.troveVersion(),
                                              trove.TROVE_VERSION)
            else:
                nvf = trv.getName(), trv.getVersion(), trv.getFlavor(), 
                err =  'Attempted to commit incomplete trove %s=%s[%s]' % nvf
                raise errors.TroveIntegrityError(error=err, *nvf)

class FilesystemRepository(DataStoreRepository, AbstractRepository):

    def __init__(self, serverNameList, troveStore, contentsDir, repositoryMap,
                 requireSigs = False):
	self.serverNameList = serverNameList
	map = dict(repositoryMap)
        for serverName in serverNameList:
            map[serverName] = self
        # XXX this client needs to die
        from conary import conarycfg
        self.reposSet = netclient.NetworkRepositoryClient(map,
                                    conarycfg.UserInformation())
	self.troveStore = troveStore

        self.requireSigs = requireSigs
        for dir in contentsDir:
            util.mkdirChain(dir)

        if len(contentsDir) == 1:
            store = DataStore(contentsDir[0])
        else:
            storeList = []
            for dir in contentsDir:
                storeList.append(DataStore(dir))

            store = DataStoreSet(*storeList)

	DataStoreRepository.__init__(self, dataStore = store)
	AbstractRepository.__init__(self)

    def close(self):
	if self.troveStore is not None:
	    self.troveStore.db.close()
	    self.troveStore = None

    ### Package access functions

    def thawFlavor(self, flavor):
        return deps.ThawFlavor(flavor)

    def hasTrove(self, pkgName, version, flavor):
	return self.troveStore.hasTrove(pkgName, troveVersion = version,
					troveFlavor = flavor)

    def getTrove(self, pkgName, version, flavor, pristine = True,
                 withFiles = True):
        return self.troveStore.getTrove(pkgName, version, flavor,
                                        withFiles = withFiles)

    def addTrove(self, pkg):
	return self.troveStore.addTrove(pkg)

    def addTroveDone(self, pkg):
	self.troveStore.addTroveDone(pkg)

    ### File functions

    def getFileVersion(self, pathId, fileId, fileVersion, withContents = 0):
	# the get trove netclient provides doesn't work with a
	# FilesystemRepository (it needs to create a change set which gets
	# passed)
	if fileVersion.getHost() not in self.serverNameList:
            # XXX This code is not needed as of version 1.0.14 of the client.
	    assert(not withContents)
	    return self.reposSet.getFileVersion(pathId, fileId, fileVersion)

	file = self.troveStore.getFile(pathId, fileId)
	if withContents:
	    if file.hasContents:
		cont = filecontents.FromDataStore(self.contentsStore,
						    file.contents.sha1())
	    else:
		cont = None

	    return (file, cont)

	return file

    def addFileVersion(self, troveInfo, pathId, fileObj, path, fileId,
                       fileVersion, fileStream = None):
	self.troveStore.addFile(troveInfo, pathId, fileObj, path, fileId,
                                fileVersion, fileStream = fileStream)

    ###

    def commitChangeSet(self, cs, mirror=False):
	# let's make sure commiting this change set is a sane thing to attempt
	for pkg in cs.iterNewTroveList():
	    v = pkg.getNewVersion()
            if v.isOnLocalHost():
                label = v.branch().label()
		raise errors.CommitError('can not commit items on '
                                         '%s label' %(label.asString()))
        self.troveStore.begin()
        if self.requireSigs:
            threshold = TRUST_FULL
        else:
            threshold = TRUST_UNTRUSTED
        try:
            # reset time stamps only if we're not mirroring.
            FilesystemChangeSetJob(self, cs, self.serverNameList,
                                   resetTimestamps = not mirror,
                                   keyCache = self.troveStore.keyTable.keyCache,
                                   threshold = threshold,
                                   mirror = mirror)
        except openpgpfile.KeyNotFound:
            # don't be quite so noisy, this is a common error
            self.troveStore.rollback()
            raise
        except:
            print >> sys.stderr, "exception occurred while committing change set"
            print >> sys.stderr, ''.join(traceback.format_exception(*sys.exc_info()))
            print >> sys.stderr, "attempting rollback"
            self.troveStore.rollback()
            raise
        else:
            self.troveStore.commit()

    def markTroveRemoved(self, name, version, flavor):
        sha1s = self.troveStore.markTroveRemoved(name, version, flavor)
        for sha1 in sha1s:
            try:
                self.contentsStore.removeFile(sha1helper.sha1ToString(sha1))
            except OSError, e:
                if e.errno != errno.ENOENT:
                    raise

    def getFileContents(self, itemList):
        contents = []

        for item in itemList:
            (fileId, fileVersion) = item[0:2]

            # the get trove netclient provides doesn't work with a
            # FilesystemRepository (it needs to create a change set which gets
            # passed)
            if fileVersion.getHost() in self.serverNameList:
                fileObj = item[2]
                cont = filecontents.FromDataStore(self.contentsStore,
                                                  fileObj.contents.sha1())
            else:
                # XXX This code is not needed as of version 1.0.14 of the 
                # client.
                #
                # a bit of sleight of hand here... we look for this file in
                # the trove it was first built in
                #
                # this could cause us to run out of file descriptors on large
                # troves. it might be better to close the file and return
                # a filecontents object?
                cont = self.reposSet.getFileContents([ item ])[0]

            contents.append(cont)

        return contents

    def createChangeSet(self, troveList, recurse = True, withFiles = True,
                        withFileContents = True, excludeAutoSource = False):
	"""
	troveList is a list of (troveName, flavor, oldVersion, newVersion,
        absolute) tuples.

	if oldVersion == None and absolute == 0, then the trove is assumed
	to be new for the purposes of the change set

	if newVersion == None then the trove is being removed
	"""
	cs = changeset.ChangeSet()

        externalTroveList = []
        externalFileList = []
        removedTroveList = []

	dupFilter = {}

	# make a copy to remove things from
	troveList = troveList[:]

        class troveListWrapper:

            def next(self):
                if not self.l and self.new:
                    # self.l (and self.trvIterator) are empty; look to
                    # self.new for new jobs we need

                    troveList = []
                    for job in self.new:
                        # do we need the old trove?
                        if job[1][0] is not None:
                            troveList.append((job[0], job[1][0], job[1][1]))

                        # do we need the new trove?
                        if job[2][0] is not None:
                            troveList.append((job[0], job[2][0], job[2][1]))

                    # flip to the new job set and it's trove iterator, and
                    # reset self.new for later additions
                    self.trvIterator = self.troveStore.iterTroves(
                                troveList, withFiles = self.withFiles,
				withFileStreams = self.withFiles)
                    self.l = self.new
                    self.new = []

                if self.l:
                    job = self.l.pop(0)

                    # Does it have an old job?
                    if job[1][0] is None:
                        old = None
			oldStreams = {}
                    else:
                        old = self.trvIterator.next()
                        if old is None:
                            # drain the iterator, in order to complete
                            # the sql queries
                            for x in self.trvIterator: pass
                            raise errors.TroveMissing(job[0], job[1][0])

			if self.withFiles:
			    old, oldStreams = old
			else:
			    oldStreams = {}

                    # Does it have a new job
                    if job[2][0] is None:
                        new = None
                        newStreams = {}
                    else:
                        new = self.trvIterator.next()
                        if new is None:
                            # drain the SQL query
                            for x in self.trvIterator: pass
                            raise errors.TroveMissing(job[0], job[2][0])

                        if self.withFiles:
                            new, newStreams = new
			else:
			    newStreams = {}

		    newStreams.update(oldStreams)
                    return job, old, new, newStreams
                else:
                    raise StopIteration

            def __iter__(self):
                while True:
                    yield self.next()

            def append(self, item):
                self.new.append(item)

            def __init__(self, l, troveStore, withFiles):
                self.trvIterator = None
                self.new = l
                self.l = []
                self.troveStore = troveStore
                self.withFiles = withFiles

        # def createChangeSet begins here

        troveWrapper = troveListWrapper(troveList, self.troveStore, withFiles)

        for job in troveWrapper:
	    (troveName, (oldVersion, oldFlavor),
		        (newVersion, newFlavor), absolute), \
			old, new, streams = job

	    # make sure we haven't already generated this changeset; since
	    # troves can be included from other troves we could try
	    # to generate quite a few duplicates
	    if dupFilter.has_key((troveName, oldFlavor, newFlavor)):
		match = False
		for (otherOld, otherNew) in \
				dupFilter[(troveName, oldFlavor, newFlavor)]:
		    if not otherOld and not oldVersion:
			same = True
		    elif not otherOld and oldVersion:
			same = False
		    elif otherOld and not oldVersion:
			same = False
		    else:
			same = otherOld == newVersion

		    if same and otherNew == newVersion:
			match = True
			break

		if match: continue

		dupFilter[(troveName, oldFlavor, newFlavor)].append(
				    (oldVersion, newVersion))
	    else:
		dupFilter[(troveName, oldFlavor, newFlavor)] = \
				    [(oldVersion, newVersion)]

	    if not newVersion:
                if oldVersion.getHost() not in self.serverNameList:
                    externalTroveList.append((troveName,
                                         (oldVersion, oldFlavor),
                                         (None, None), absolute))
                else:
                    # remove this trove and any trove contained in it
                    cs.oldTrove(troveName, oldVersion, oldFlavor)
                    for (name, version, flavor) in \
                                            old.iterTroveList(strongRefs=True):
                        troveWrapper.append((name, (version, flavor),
                                                (None, None), absolute))
		continue

            if (newVersion.getHost() not in self.serverNameList
                or (oldVersion and
                    oldVersion.getHost() not in self.serverNameList)):
                # don't try to make changesets between repositories; the
                # client can do that itself

                # we don't generate chagnesets between removed and
                # present troves; that's up to the client
                externalTroveList.append((troveName, (oldVersion, oldFlavor),
                                     (newVersion, newFlavor), absolute))
                continue
            elif (oldVersion and old.type() == trove.TROVE_TYPE_REMOVED):
                removedTroveList.append((troveName, (oldVersion, oldFlavor),
                                        (newVersion, newFlavor), absolute))
                continue

	    (troveChgSet, filesNeeded, pkgsNeeded) = \
				new.diff(old, absolute = absolute)

	    if recurse:
                for (pkgName, (old, oldFlavor), (new, newFlavor),
                                isAbsolute) in pkgsNeeded:
		    troveWrapper.append((pkgName, (old, oldFlavor),
					       (new, newFlavor), absolute))

	    cs.newTrove(troveChgSet)

	    # sort the set of files we need into bins based on the server
	    # name
	    serverIdx = {}
            getList = []
            localFilesNeeded = []

	    for (pathId, oldFileId, oldFileVersion, newFileId, newFileVersion) in filesNeeded:
                # if either the old or new file version is on a different
                # repository, creating this diff is someone else's problem
                if (newFileVersion.getHost() not in self.serverNameList
                    or (oldFileVersion and
                        oldFileVersion.getHost() not in self.serverNameList)):
                    externalFileList.append((pathId, troveName,
                         (oldVersion, oldFlavor, oldFileId, oldFileVersion),
                         (newVersion, newFlavor, newFileId, newFileVersion)))
                else:
                    localFilesNeeded.append((pathId, oldFileId, oldFileVersion,
                                             newFileId, newFileVersion))
                    if oldFileVersion:
                        getList.append((pathId, oldFileId, oldFileVersion))
                    getList.append((pathId, newFileId, newFileVersion))

            # Walk this in reverse order. This may seem odd, but the
            # order in the final changeset is set by sorting that happens
            # in the change set object itself. The only reason we sort
            # here at all is to make sure PTR file types come before the
            # file they refer to. Reverse shorting makes this a bit easier.
            localFilesNeeded.sort()
            localFilesNeeded.reverse()

            ptrTable = {}
            for (pathId, oldFileId, oldFileVersion, newFileId, \
                 newFileVersion) in localFilesNeeded:
		oldFile = None
		if oldFileVersion:
		    #oldFile = idIdx[(pathId, oldFileId)]
		    oldFile = files.ThawFile(streams[oldFileId], pathId)

		oldCont = None
		newCont = None

		#newFile = idIdx[(pathId, newFileId)]
		newFile = files.ThawFile(streams[newFileId], pathId)

		(filecs, contentsHash) = changeset.fileChangeSet(pathId,
                                                                 oldFile,
                                                                 newFile)

		cs.addFile(oldFileId, newFileId, filecs)

                if not withFileContents or (excludeAutoSource and
                   newFile.flags.isAutoSource()):
                    continue

		# this test catches files which have changed from not
		# config files to config files; these need to be included
		# unconditionally so we always have the pristine contents
		# to include in the local database
		if (contentsHash or (oldFile and newFile.flags.isConfig()
                                      and not oldFile.flags.isConfig())):
		    if oldFileVersion and oldFile.hasContents:
			oldCont = self.getFileContents(
                            [ (oldFileId, oldFileVersion, oldFile) ])[0]

		    newCont = self.getFileContents(
                            [ (newFileId, newFileVersion, newFile) ])[0]

		    (contType, cont) = changeset.fileContentsDiff(oldFile,
						oldCont, newFile, newCont)

                    # we don't let config files be ptr types; if they were
                    # they could be ptrs to things which aren't config files,
                    # which would completely hose the sort order we use. this
                    # could be relaxed someday to let them be ptr's to other
                    # config files
                    if not newFile.flags.isConfig() and \
                                contType == changeset.ChangedFileTypes.file:
                        contentsHash = newFile.contents.sha1()
                        ptr = ptrTable.get(contentsHash, None)
                        if ptr is not None:
                            contType = changeset.ChangedFileTypes.ptr
                            cont = filecontents.FromString(ptr)
                        else:
                            ptrTable[contentsHash] = pathId

                    if not newFile.flags.isConfig() and \
                                contType == changeset.ChangedFileTypes.file:
                        cont = filecontents.CompressedFromDataStore(
                                              self.contentsStore,
                                              newFile.contents.sha1())
                        compressed = True
                    else:
                        compressed = False

                    # ptr entries are not compressed, whether or not they
                    # are config files. override the compressed rule from
                    # above
                    if contType == changeset.ChangedFileTypes.ptr:
                        compressed = False

		    cs.addFileContents(pathId, contType, cont,
				       newFile.flags.isConfig(),
                                       compressed = compressed)

	return (cs, externalTroveList, externalFileList, removedTroveList)
