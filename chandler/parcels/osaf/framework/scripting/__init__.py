__copyright__ = "Copyright (c) 2005-2006 Open Source Applications Foundation"
__license__ = "http://osafoundation.org/Chandler_0.1_license_terms.htm"

import logging
import wx

from application import schema, Globals

from osaf import pim
from osaf.usercollections import UserCollection

from i18n import OSAFMessageFactory as _

# these are all the sub-modules that come together here
from script import cats_profiler, hotkey_script, \
     run_script_with_symbols, run_startup_script_with_symbols, \
     Script, script_file
import User
from proxy import app_ns

"""
This is the main module for scripting, and ties in multiple scripting components:
- basic loading and running of scripts (script.py)
- detail view blocks (blocks.py)
- User-level emulation (typing, and such) (User.py)
- app-level scripting (App and Block proxies - this file)

"""


__all__ = [
    'app_ns', 'cats_profiler', 'hotkey_script', 
    'run_script', 'run_startup_script', 'Script', 'script_file',
    'User'
]

logger = logging.getLogger(__name__)

def installParcel(parcel, oldVersion=None):

    scripts = pim.KindCollection.update(parcel, 'scripts',
        kind=Script.getKind(parcel.itsView)
    )

    scriptsCollection = \
        pim.SmartCollection.update(parcel, 'scriptsCollection',
            displayName = _(u"Scripts"),
            renameable = False,
            private = False,
            source=scripts
            )
    userScripts = UserCollection(scriptsCollection)
    userScripts.dontDisplayAsCalendar = True
    

    from blocks import installBlocks
    installBlocks(parcel, oldVersion)


# these are essentially wrappers around run_script_* that add app_ns and User
script_builtins = {'app_ns':app_ns, 'User':User }

def run_script(*args, **kwds):
    builtIns = kwds.pop('builtIns', {})
    builtIns.update(script_builtins)
    run_script_with_symbols(builtIns=builtIns, *args, **kwds)


def run_startup_script(*args, **kwds):
    builtIns = kwds.pop('builtIns', {})
    builtIns.update(script_builtins)
    run_startup_script_with_symbols(builtIns=builtIns, *args, **kwds)
    
