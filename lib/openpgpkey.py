#!/usr/bin/python2.4
from Crypto.PublicKey import DSA
from Crypto.PublicKey import RSA
from openpgpfile import getPrivateKey
from openpgpfile import getPublicKey
from openpgpfile import getFingerprint

#-----#
#OpenPGPKey structure:
#     cyptoKey:         class  (either DSA or RSA object)
#     fingerprint:      string key fingerprint of this key
#     revoked:          bool   indicates if key is revoked
#     trustLevel:       int    Higher is more trusted
#                              0 is untrusted
#                              -1 is ultimate trust
#-----#

class OpenPGPKey:
    def __init__(self, keyId, private, passPhrase = '', keyFile = ''):
        ###change when implement revocation functionality
        self.revoked=0
        ###change when implement trust levels
        self.trustLevel = -1
        #translate the keyId to the fingerprint for consistency
        self.fingerprint = getFingerprint (keyId)
        if private:
            self.cryptoKey = getPrivateKey(keyId, passPhrase, keyFile)
        else:
            self.cryptoKey = getPublicKey(keyId, keyFile)

    def getTrustLevel(self):
        return self.trustLevel

    def isRevoked(self):
        return self.revoked

    def getFingerprint(self):
        return self.fingerprint

    def _RandFunc(self, N):
        rand=open('/dev/random','r')
        r=rand.read(N)
        rand.close()
        return r

    def signString(self, data):
        if 'DSAobj_c' in self.cryptoKey.__class__.__name__:
            K = self.cryptoKey.q + 1
            while K > self.cryptoKey.q:
                K= getPrime( 160, self._RandFunc)
        else:
            K=0
        return self.cryptoKey.sign( data, K )

    def verifyString(self, data, sig):
        return self.cryptoKey.verify( data, sig )

class OpenPGPPublicKey(OpenPGPKey):
    def __init__ (self, keyId, keyFile = ''):
        OpenPGPKey.__init__(self, keyId, 0, '', keyFile)

class OpenPGPPrivateKey(OpenPGPKey):
    def __init__ (self, keyId, passPhrase = '', keyFile = ''):
        OpenPGPKey.__init__(self, keyId, 1, passPhrase, keyFile)




#code to execute if file is booted directly
if __name__ == "__main__":
    key=OpenPGPPrivateKey('DA44E4BD','111111','/home/smg/.gnupg/secring.gpg')
    sig=key.signString('crap')
    print key.getFingerprint()
    print key.verifyString('crap',sig)
