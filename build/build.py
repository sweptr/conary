#
# Copyright (c) 2004 Specifix, Inc.
# All rights reserved
#
import os
import shutil
import util
import string

# Note: when creating templates, be aware that they are evaulated
# twice, in the context of two different dictionaries.
#  o  keys from keywords should have a # single %, as should "args".
#  o  keys passed in through the macros argument will need %% to
#     escape them for delayed evaluation.  This will include at
#     least %%(builddir)s for all, and doInstall will also get
#     %%(destdir)s

class ShellCommand:
    def __init__(self, *args, **keywords):
        # initialize initialize our keywords to the defaults
        self.__dict__.update(self.keywords)
        # check to make sure that we don't get a keyword we don't expect
        for key in keywords.keys():
            if key not in self.keywords.keys():
                raise TypeError, ("%s.__init__() got an unexpected keyword argument "
                                  "'%s'" % (self.__class__.__name__, key))
        # copy the keywords into our dict, overwriting the defaults
        self.__dict__.update(keywords)
        self.args = string.join(args)
        # pre-fill in the preMake and arguments
        self.command = self.template % self.__dict__



class Automake(ShellCommand):
    # note: no use of %(args)s -- which command would it apply to?
    template = ('cd %%(builddir)s; '
                'aclocal %%(m4DirArgs)s %(acLocalArgs)s; '
		'%(preAutoconf)s autoconf %(autoConfArgs)s; '
		'automake %(autoMakeArgs)s')
    keywords = {'autoConfArgs': '--force',
                'autoMakeArgs': '--copy --force',
		'acLocalArgs': '',
		'preAutoconf': '',
                'm4Dir': ''}
    
    def doBuild(self, macros):
	macros = macros.copy()
        if self.m4Dir:
	    macros.update({'m4DirArgs': '-I %s' %(self.m4Dir)})
        util.execute(self.command %macros)


class Configure(ShellCommand):
    template = ('cd %%(builddir)s; '
                '%%(mkObjdir)s '
		'%(preConfigure)s %%(configure)s '
		'  --prefix=%%(prefix)s '
		'  --bindir=%%(bindir)s '
                '  --sysconfdir=%%(sysconfdir)s '
		'  --datadir=%%(datadir)s '
		'  --mandir=%%(mandir)s --infodir=%%(infodir)s '
		'  %(args)s')
    keywords = {'preConfigure': '',
                'objDir': ''}
    
    def doBuild(self, macros):
	macros = macros.copy()
        if self.objDir:
            macros['mkObjdir'] = 'mkdir -p %s; cd %s;' \
	                         %(self.objDir, self.objDir)
	    macros['configure'] = '../configure'
        else:
            macros['configure'] = './configure'
        util.execute(self.command %macros)

class ManualConfigure(Configure):
    template = ('cd %%(builddir)s; '
                '%%(mkObjdir)s '
	        '%(preConfigure)s %%(configure)s %(args)s')

class Make(ShellCommand):
    template = 'cd %%(builddir)s; %(preMake)s make %%(mflags)s %%(parallelmflags)s %(args)s'
    keywords = {'preMake': ''}
    
    def doBuild(self, macros):
	macros = macros.copy()
        util.execute(self.command %macros)

class MakeInstall(ShellCommand):
    template = ('cd %%(builddir)s; '
                '%(preMake)s make %%(mflags) %(rootVar)s=%%(destdir)s %(installtarget)s %(args)s')
    keywords = {'rootVar': 'DESTDIR',
                'preMake': '',
		'installtarget': 'install'}

    def doInstall(self, macros):
	util.execute(self.command %macros)

class InstallFile:

    # make sure that the decimal value really is unreasonable before
    # adding a new translation to this file.
    permmap = {
	1755: 01755,
	4755: 04755,
	755: 0755,
	750: 0750,
	644: 0644,
	640: 0640,
    }

    def doInstall(self, macros):
	dest = macros['destdir'] + self.toFile %macros
	util.mkdirChain(os.path.dirname(dest))

	for fromFile in self.fromFiles:
	    thisdest = dest
	    if dest[-1:] == '/':
		thisdest = dest + fromFile
	    shutil.copyfile(fromFile, thisdest)
	    os.chmod(thisdest, self.mode)

    def __init__(self, fromFiles, toFile, perms = 0644):
	self.toFile = toFile
	if type(fromFiles) is str:
	    self.fromFiles = (fromFiles,)
	else:
	    self.fromFiles = fromFiles
	# notice obviously broken permissions
	if self.permmap.has_key(perms):
	    print 'odd permission %o, correcting to %o: add initial "0"?' \
	          %(perms, permmap[perms])
	    perms = permmap[perms]
	self.mode = perms

class InstallSymlink:

    def doInstall(self, macros):
	dest = macros['destdir'] + self.toFile %macros
	util.mkdirChain(os.path.dirname(dest))
	os.symlink(self.fromFile, macros['destdir'] + self.toFile %macros)

    def __init__(self, fromFile, toFile):
	self.fromFile = fromFile
	self.toFile = toFile

class RemoveFiles:

    def doInstall(self, macros):
	if self.recursive:
	    util.execute("rm -rf %s/%s" %(macros['destdir'], self.filespec %macros))
	else:
	    util.execute("rm -f %s/%s" %(macros['destdir'], self.filespec %macros))

    def __init__(self, filespec, recursive=0):
	self.filespec = filespec
	self.recursive = recursive

class MoveFile:

    def doInstall(self, macros):
	dest = macros['destdir'] + self.toFile %macros
	util.mkdirChain(os.path.dirname(dest))
	os.rename(macros['destdir'] + self.fromFile %macros,
	          macros['destdir'] + self.toFile %macros)

    def __init__(self, fromFile, toFile):
	self.fromFile = fromFile
	self.toFile = toFile
