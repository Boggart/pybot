import gevent
import ircbot
import signal

if __name__ == '__main__':
    
    SETTINGS = {
        'server': 'irc.rizon.net', 
        'nick': 'pingsky', 
        'realname': 'Officer Pingsky', 
        'port': 6697, 
        'ssl': True, 
        'channels': ['#botbus'], 
        }
    
    bot = lambda : ircbot.Irc(SETTINGS)
    jobs = [gevent.spawn(bot)]
    try:
        gevent.signal(signal.SIGQUIT, gevent.kill)
    except AttributeError:
        print "Windows doesn't support SIGQUIT, watching for SIGTERM instead."
        gevent.signal(signal.SIGTERM, gevent.kill)
    gevent.joinall(jobs)