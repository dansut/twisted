# Twisted, the Framework of Your Internet
# Copyright (C) 2001 Matthew W. Lefkowitz
# 
# This library is free software; you can redistribute it and/or
# modify it under the terms of version 2.1 of the GNU Lesser General Public
# License as published by the Free Software Foundation.
# 
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from twisted.python.failure import Failure
from twisted.spread import pb

from twisted.im.locals import ONLINE, OFFLINE, AWAY

import basesupport

class TwistedWordsPerson(basesupport.AbstractPerson):
    """I a facade for a person you can talk to through a twisted.words service.
    """
    def __init__(self, name, wordsClient, chatui):
        basesupport.AbstractPerson.__init__(self, name, wordsClient, chatui)
        self.status = OFFLINE

    def isOnline(self):
        return ((self.status == ONLINE) or
                (self.status == AWAY))

    def getStatus(self):
        return ((self.status == ONLINE) and "Online" or "Away")

    def sendMessage(self, text, metadata):
        """Return a deferred...
        """
        if metadata:
            d=self.client.perspective.directMessage(self.name,
                                                     text, metadata)
            d.addErrback(self.metadataFailed, "* "+text)
            return d
        else:
            return self.client.perspective.callRemote('directMessage',self.name, text)

    def metadataFailed(self, result, text):
        print "result:",result,"text:",text
        return self.client.perspective.directMessage(self.name, text)


    def setStatus(self, status):
        self.status = status
        self.chat.getContactsList().setContactStatus(self)

class TwistedWordsGroup(basesupport.AbstractGroup):
    def __init__(self, name, wordsClient, chatui):
        basesupport.AbstractGroup.__init__(name, wordsClient, chatui)
        self.joined = 0

    def sendGroupMessage(self, text, metadata=None):
        """Return a deferred.
        """
        #for backwards compatibility with older twisted.words servers.
        if metadata:
            d=self.client.perspective.callRemote('groupMessage', self.name,
                                                  text, metadata)
            d.addErrback(self.metadataFailed, "* "+text)
            return d
        else:
            return self.client.perspective.callRemote('groupMessage',
                                                      self.name, text)

    def setTopic(self, text):
        self.client.perspective.callRemote(
            'setGroupMetadata',
            {'topic': text, 'topic_author': self.client.name},
            self.name)

    def metadataFailed(self, result, text):
        print "result:",result,"text:",text
        return self.client.perspective.callRemote('groupMessage', self.name, text)

    def joining(self):
        self.joined = 1

    def leaving(self):
        self.joined = 0

    def leave(self):
        return self.client.perspective.callRemote('leaveGroup', self.name)



class TwistedWordsClient(pb.Referenceable):
    """In some cases, this acts as an Account, since it a source of text
    messages (multiple Words instances may be on a single PB connection)
    """
    def __init__(self, acct, serviceName, perspectiveName, chatui):
        self.accountName = "%s (%s:%s)" % (acct.accountName, serviceName, perspectiveName)
        self.name = perspectiveName
        print "HELLO I AM A PB SERVICE", serviceName, perspectiveName
        self.chat = chatui

    def getGroup(self, name):
        return self.chat.getGroup(name, self, TwistedWordsGroup)

    def getGroupConversation(self, name):
        return self.chat.getGroupConversation(self.getGroup(name))

    def addContact(self, name):
        self.perspective.callRemote('addContact', name)

    def remote_receiveGroupMembers(self, names, group):
        print 'received group members:', names, group
        self.getGroupConversation(group).setGroupMembers(names)

    def remote_receiveGroupMessage(self, sender, group, message, metadata=None):
        print 'received a group message', sender, group, message, metadata
        self.getGroupConversation(group).showGroupMessage(sender, message, metadata)

    def remote_memberJoined(self, member, group):
        print 'member joined', member, group
        self.getGroupConversation(group).memberJoined(member)

    def remote_memberLeft(self, member, group):
        print 'member left'
        self.getGroupConversation(group).memberLeft(member)

    def remote_notifyStatusChanged(self, name, status):
        self.chat.getPerson(name, self, TwistedWordsPerson).setStatus(status)

    def remote_receiveDirectMessage(self, name, message, metadata=None):
        self.chat.getConversation(self.chat.getPerson(name, self, TwistedWordsPerson)).showMessage(message, metadata)

    def remote_receiveContactList(self, clist):
        for name, status in clist:
            self.chat.getPerson(name, self, TwistedWordsPerson).setStatus(status)

    def remote_setGroupMetadata(self, dict_, groupName):
        if dict_.has_key("topic"):
            self.getGroupConversation(groupName).setTopic(dict_["topic"], dict_.get("topic_author", None))

    def joinGroup(self, name):
        self.getGroup(name).joining()
        return self.perspective.callRemote('joinGroup', name).addCallback(self._cbGroupJoined, name)

    def leaveGroup(self, name):
        self.getGroup(name).leaving()
        return self.perspective.callRemote('leaveGroup', name).addCallback(self._cbGroupLeft, name)

    def _cbGroupJoined(self, result, name):
        groupConv = self.chat.getGroupConversation(self.getGroup(name))
        groupConv.showGroupMessage("sys", "you joined")
        self.perspective.callRemote('getGroupMembers', name)

    def _cbGroupLeft(self, result, name):
        print 'left',name
        groupConv = self.chat.getGroupConversation(self.getGroup(name), 1)
        groupConv.showGroupMessage("sys", "you left")

    def connected(self, perspective):
        print 'Connected Words Client!', perspective
        self.chat.registerAccountClient(self)
        self.perspective = perspective
        self.chat.getContactsList()



pbFrontEnds = {
    "twisted.words": TwistedWordsClient,
    "twisted.reality": None
    }


class PBAccount(basesupport.AbstractAccount):
    _isOnline = 0
    gatewayType = "PB"
    def __init__(self, accountName, autoLogin,
                 host, port, identity, password, services):
        self.accountName = accountName
        self.autoLogin = autoLogin
        self.password = password
        self.host = host
        self.port = port
        self.identity = identity
        self.services = []
        for serviceType, serviceName, perspectiveName in services:
            self.services.append([pbFrontEnds[serviceType], serviceName,
                                  perspectiveName])

    def startLogOn(self, chatui):
        print 'Connecting...',
        pb.getObjectAt(self.host, self.port).addCallbacks(self._cbConnected,
                                                          self._ebConnected,
              
                                            callbackArgs=(chatui,))

    def _cbConnected(self, root, chatui):
        print 'Connected!'
        print 'Identifying...',
        pb.authIdentity(root, self.identity, self.password).addCallbacks(
            self._cbIdent, self._ebConnected, callbackArgs=(chatui,))

    def _cbIdent(self, ident, chatui):
        if not ident:
            print 'falsely identified.'
            return self._ebConnected(Failure(Exception("username or password incorrect")))
        print 'Identified!'
        for handlerClass, sname, pname in self.services:
            handler = handlerClass(self, sname, pname, chatui)
            ident.callRemote('attach', sname, pname, handler).addCallback(handler.connected)

    def _ebConnected(self, error):
        print 'Not connected.'
        return error

