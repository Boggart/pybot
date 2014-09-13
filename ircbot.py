import gevent
import time
import sys
from gevent import socket, queue, pool
from gevent.ssl import wrap_socket

#Connection class
class Connection(object):
    '''Handles TCP connections, `timeout` is in secs.'''
    def __init__(self, host, port, ssl=False, timeout=300):
        self._inBuffer = ''
        self._outBuffer = ''
        self.inQueue = gevent.queue.Queue()
        self.outQueue = gevent.queue.Queue()
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket = self._createSocket(ssl)

    def _createSocket(self, ssl):
        if ssl:
            return gevent.ssl.wrap_socket(gevent.socket.socket(), server_side=False)
        else:
            return gevent.socket.socket()

    def connect(self):
        print 'Connecting to ' + self.host + ":" + str(self.port)
        self._socket.connect((self.host, self.port))
        print 'Connected.'
        try:
            jobs = [gevent.spawn(self._recvLoop), gevent.spawn(self._sendLoop)]
            gevent.joinall(jobs)
        finally:
            gevent.killall(jobs)

    def disconnect(self):
        self._socket.close()

    def _recvLoop(self):
        while True:
            data = self._socket.recv(4096)
            self._inBuffer += data

            while '\r\n' in self._inBuffer:
                line, self._inBuffer = self._inBuffer.split('\r\n', 1)
                self.inQueue.put(line)

    def _sendLoop(self):
        while True:
            line = self.outQueue.get().splitlines()[0][:500]
            self._outBuffer += line.encode('utf-8', 'replace') + '\r\n'
                
            while self._outBuffer:
                sent = self._socket.send(self._outBuffer)
                self._outBuffer = self._outBuffer[sent:]

#Plugin class
class Plugin(gevent.Greenlet):

    def __init__(self):
        self.master = None
        self.name = 'Plugin'
        self.inbox = gevent.queue.Queue()
        gevent.Greenlet.__init__(self)

    def process(self, line):
        """
        Define in your subclass.
        """
        raise NotImplemented()

    def run(self):
        self.running = True
        while self.running:
            try:
                line = self.inbox.get()
            except gevent.queue.Empty:
                gevent.sleep()
            self.process(line)

class HelloPlugin(Plugin):
    def __init__(self):
        self.name = 'HelloPlugin'
        Plugin.__init__(self)

    def process(self, line):
        args = [word.lower() for word in line['args']]
        if line['command'] == 'PRIVMSG' and (('hello %s' % self.master.nick) in line['args']):
            self.master.msg('#botbus', 'Hello %s.' % line['nick'])
        return

class Message(object):
    def __init__(self):
        self.type = None

#Bot class
class Irc(object):
    '''Provides a basic interface to an IRC server.'''
    
    def __init__(self, settings):
        self.server = settings['server']
        self.plugins = [HelloPlugin()]
        self.nick = settings['nick']
        if 'altNick' not in settings:
            self.altNick = None
        else:
            self.altNick = settings['altNick']
        self.realname = settings['realname']
        self.port = settings['port']
        self.ssl = settings['ssl']
        self.channels = settings['channels']
        self.line = {'prefix': '', 'command': '', 'args': ['', '']}
        self.lines = gevent.queue.Queue()
        self.timestamp = time.time()

        if not self.ssl:
            self.ssl = False
        
        self._connect()
        self._loadPlugins()
        self._eventLoop()

    def _connect(self):
        self.conn = Connection(self.server, self.port, self.ssl)
        gevent.spawn(self.conn.connect)
        self.cmd('USER', ' '.join((self.nick, self.nick, self.nick, (':'+ self.realname))))
        self._set_nick(self.nick)
    
    def _disconnect(self):
        self.conn.disconnect()

    def _loadPlugins(self):
        print 'Loading Plugins...'
        for plugin in self.plugins:
            print 'Starting Plugin: %s' % plugin.name
            plugin.master = self
            plugin.start()



    def _parseMsg(self, s):
        '''
        Breaks a message from an IRC server into its nick, hostmask,
        command, and arguments.
        '''
        
        prefix = ''
        trailing = []
        if not s:
            raise 'Received an empty line from the server.'
        if s[0] == ':':
            prefix, s = s[1:].split(' ', 1)
        if s.find(' :') != -1:
            s, trailing = s.split(' :', 1)
            args = s.split()
            args.append(trailing)
        else:
            args = s.split()
        command = args.pop(0)

        if "!" not in prefix:
            nick = prefix
            hostmask = prefix
        else:
            nick, hostmask = prefix.split('!')

        return nick, hostmask, command, args

    def _eventLoop(self):
        '''
        The main event loop.
        
        Data from the server is parsed here using `parseMsg`. Parsed events
        are put in the object's event queue, `self.events`.
        '''
        
        while True:
            try:
                line = self.conn.inQueue.get()
            except gevent.queue.Empty:
                line = ''
            self.timestamp = time.time()

            if len(line) > 0:
                nick, hostmask, command, args = self._parseMsg(line)

                line = {'timestamp': self.timestamp, 'nick': nick, 'hostmask': hostmask, 'command': command, 'args': args}
                #print line
                if nick != self.nick:
                    self.lines.put(line)

                #No use having this stuff in a plugin, it's always needed anyway.
                if command == '433': # nick in use
                    if self.altNick:
                        self.nick = self.altNick
                    else:
                        self.nick = self.nick + '_'
                    self._set_nick(self.nick)

                if command == 'PING':
                    self.cmd('PONG', args)

                if command == '001': #Good to go, join channels.
                    print 'USER and NICK accepted at %s, good to join.' % time.ctime(self.timestamp)
                    self._join_chans(self.channels)

            for plugin in self.plugins:
                plugin.inbox.put(line)

            gevent.sleep(0.1)
                

    
    def _set_nick(self, nick):
        self.cmd('NICK', nick)
    
    def _join_chans(self, channels):
        return [self.cmd('JOIN', channel) for channel in channels]
    
    def reply(self, prefix, msg):
        self.msg(prefix.split('!')[0], msg)
    
    def msg(self, target, msg):
        self.cmd('PRIVMSG', (target + ' :' + msg))
    
    def cmd(self, command, args, prefix=None):
        
        if prefix:
            self._send(prefix + command + ' ' + ''.join(args))
        else:
            self._send(command + ' ' + ''.join(args))
            
    def _send(self, s):
        print(s)
        self.conn.outQueue.put(s)