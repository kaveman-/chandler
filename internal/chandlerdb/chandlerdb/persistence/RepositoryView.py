#   Copyright (c) 2004-2007 Open Source Applications Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from __future__ import with_statement
import logging, sys, gc, threading, os, time, contextlib

from Queue import Queue
from heapq import heapify, heappop
from pkg_resources import resource_stream
from PyICU import ICUtzinfo, FloatingTZ

from chandlerdb.util.c import UUID, isuuid, Nil, Default, CLinkedMap
from chandlerdb.item.c import CItem
from chandlerdb.persistence.c import CView

from chandlerdb.util.Path import Path
from chandlerdb.util.Lob import Lob
from chandlerdb.util.ClassLoader import ClassLoader
from chandlerdb.persistence.RepositoryError import *
from chandlerdb.item.Item import Item, MissingClass
from chandlerdb.item.Children import Children
from chandlerdb.item.Indexes import NumericIndex, SortedIndex
from chandlerdb.item.Indexed import Indexed
from chandlerdb.item.RefCollections import RefList


def otherViewWins(code, item, attribute, value):
    """
    "Other view wins" merge function.

    A merge function to use with
    L{refresh<chandlerdb.persistence.RepositoryView.refresh>} or
    L{commit<chandlerdb.persistence.RepositoryView.commit>} to let the
    changes that are coming in during refresh to win a conflict over the
    calling view's changes.
    """

    if code == MergeError.DELETE:
        return True                             # Let the item delete 
                                                # in the other view win

    return getattr(item, attribute, Nil)        # Let changes from
                                                # other views win


def thisViewWins(code, item, attribute, value):
    """
    "This view wins" merge function.

    A merge function to use with
    L{refresh<chandlerdb.persistence.RepositoryView.refresh>} or
    L{commit<chandlerdb.persistence.RepositoryView.commit>} to let this
    view's changes win a conflict over the changes that coming in during
    refresh.

    However, if an item was deleted in another view, and this view has
    changes on it, they still will be lost to the other view.
    """

    if code == MergeError.DELETE:
        return True                             # Let the item delete 
                                                # in the other view win

    return value                                # Let changes from the
                                                # this view win

class CurrentView(threading.local):
    view = None

    @contextlib.contextmanager
    def set(self, view):
        try:
            prev = self.view
            self.view = view
            yield view
        finally:
            self.view = prev

    def get(self):
        return self.view

currentview = CurrentView()


class RepositoryView(CView):
    """
    This class implements the cache for loaded items. Changes to items in a
    view are not written into persistent storage until the view is
    committed. A view will not see changes in the repository made by other
    views until the view is refreshed, for example before a L{commit}.
    """
    
    # 0.5.0: first tracked core schema version
    # 0.5.1: added indexes to abstract sets
    # 0.5.2: renamed 'persist' aspect to 'persisted', added 'indexed' aspect
    # 0.5.3: new monitor implementation
    # 0.5.4: BString and UString types renamed to Bytes and Text
    # 0.5.5: added //Schema/Core/Type.types to get rid of type kind query
    # 0.5.6: added support for Kind extents
    # 0.5.7: added support for Kind inheritedSuperKinds cache
    # 0.5.8: added complete attribute cache
    # 0.5.9: removed repository.query.Query and Query kind
    # 0.5.10: added Importable type
    # 0.5.11: removed inheritedAttributes transient cache
    # 0.6.1: watcherDispatch layout changed
    # 0.6.2: added 'notify' aspect
    # 0.6.3: added Collection 'export' cloud with 'subscribers' endpoint
    # 0.6.4: changed format of some indexes to accept one or more attributes
    # 0.6.5: changed format of abstract sets to store an optional id
    # 0.6.6: added support for MethodFilteredSet
    # 0.6.7: watchers reworked to use RefDict
    # 0.6.8: removed support for persistent collection queue subscriptions
    # 0.6.9: added 'afterChange' attribute aspect
    # 0.6.10: added new enumeration type: ConstantEnumeration
    # 0.6.11: removed Kind inheritedSuperKinds transient cache
    # 0.6.12: removed 'persisted' aspect
    # 0.6.13: added 'literal' endpoint include policy
    # 0.6.14: added support for 'init' monitor op
    # 0.6.15: added IndexMonitor class
    # 0.6.16: added support for python's decimal.Decimal type
    # 0.6.17: removed item import/export code and clouds
    # 0.6.18: removed 'displayName' and 'displayAttribute' from core schema
    # 0.6.19: added WITHSCHEMA flag
    # 0.6.20: replaced SingleRef with ItemRef
    # 0.6.21: removed support for 'redirectTo' attribute aspect
    # 0.6.22: added support for 'inheritFrom' instance-specific inheritance
    # 0.6.23: added NilValue type for persisting Empty and Default
    # 0.6.24: monitor rework to support deferred re-indexing
    # 0.6.25: monitor rework to support inheritance with filters
    # 0.6.26: removed 'otherNames' otherName override from Kind
    # 0.7.0: rolling over to version 0.7
    # 0.7.1: added 'notify' attribute to Kind, like Attribute's
    # 0.7.2: DateTime and Time types now implement custom == compare
    # 0.7.3: added support for attribute correlations
    
    CORE_SCHEMA_VERSION = 0x00070300

    def __init__(self, repository, name=None, version=None,
                 deferDelete=Default, pruneSize=Default, notify=True,
                 mergeFn=None, timezone=Default, ontzchange=None):
        """
        Initializes a repository view.

        This contructor should not be invoked directly but the
        L{createView<chandlerdb.persistence.Repository.Repository.createView>}
        method should be used instead so that the appropriate view
        implementation for the repository be used.
        """

        if not name:
            name = threading.currentThread().getName()

        if repository is not None:
            if not repository.isOpen():
                raise RepositoryError, "Repository is not open"

            if pruneSize is Default:
                self.pruneSize = repository.pruneSize
            else:
                self.pruneSize = pruneSize

        super(RepositoryView, self).__init__(repository, name,
                                             RepositoryView.itsUUID)
        self._mergeFn = None
        self.openView(version, deferDelete, notify, mergeFn,
                      timezone, ontzchange)
        
    def _isNullView(self):

        return False

    def _createRefList(self, item, name, otherName, dictKey, 
                       readOnly, new, uuid):

        raise NotImplementedError, "%s._createRefList" %(type(self))
    
    def _createChildren(self, parent, new):

        raise NotImplementedError, "%s._createChildren" %(type(self))
    
    def _getLobType(self):

        raise NotImplementedError, "%s._getLobType" %(type(self))

    def createLob(self, data, *args, **kwds):

        return self['Schema']['Core']['Lob'].makeValue(data, *args, **kwds)

    def openView(self, version=None, deferDelete=Default, notify=Default,
                 mergeFn=None, timezone=Default, ontzchange=None):
        """
        Open this repository view.

        A view is created open, calling this method is only necessary when
        re-opening a closed view.
        """

        repository = self.repository

        if repository is not None:
            if version is None:
                version = repository.store.getVersion()
            elif version < repository.store.getMinVersion():
                raise ValueError, (version, 'no longer exists')
            verify = repository._isVerify()
            if timezone is None:
                timezone = repository.timezone
            if ontzchange is None:
                ontzchange = repository.ontzchange
        else:
            if version is None:
                version = 0
            verify = False

        if verify:  # set VERIFY bit, clearing others
            self._status = RepositoryView.VERIFY
        else:       # leave VERIFY bit as is, clearing others
            self._status &= RepositoryView.VERIFY

        if notify is True:
            self._status &= ~RepositoryView.DONTNOTIFY
        elif notify is False:
            self._status |= RepositoryView.DONTNOTIFY

        if mergeFn is not None:
            self.setMergeFn(mergeFn)

        self._queuedNotifications = Queue()
        self._newIndexes = []

        self._version = long(version)
        self._roots = self._createChildren(self, version == 0)
        self._registry = {}
        self._refRegistry = {}
        self._deletedRegistry = {}
        self._instanceRegistry = {}
        self._loadingRegistry = {}
        self._status |= RepositoryView.OPEN
        self.tzinfo = None

        if deferDelete is Default:
            deferDelete = repository._deferDelete
        self._deferDelete = deferDelete
        if self._deferDelete:
            self.deferDelete()

        self.classLoader = ClassLoader(Item, MissingClass)

        if repository is not None:
            if repository.isRefCounted():
                self._status |= RepositoryView.REFCOUNTED
            repository.store.attachView(self)
            repository._openViews.append(self)

        # timezone may be set to Default to use whatever is persisted
        tzid = self._loadTimezone()
        if tzid:
            origtz = ICUtzinfo.getInstance(tzid)
            self.tzinfo = ViewTZInfo(self, origtz, ontzchange)
            if timezone:
                self.tzinfo.default = timezone
        else:
            self.tzinfo = ViewTZInfo(self, timezone, ontzchange)
        
        self._loadSchema()

    def setMergeFn(self, mergeFn):

        self._mergeFn = mergeFn

    def _loadTimezone(self, version=None):

        if version is None:
            version = self.itsVersion

        if version:
            tzid = self.store.getViewTimezone(version)
        else:
            tzid = None

        tzinfo = self.tzinfo
        if not (tzid is None or tzinfo is None):
            tzinfo.setDefault(tzinfo.getInstance(tzid))

        return tzid

    def _loadSchema(self):

        schema = self.findPath('Packs/Schema')

        if schema is None:
            schema = self.loadPack('packs/schema.pack', package='chandlerdb')
            schema.version = RepositoryView.CORE_SCHEMA_VERSION

        return schema

    def __nonzero__(self):

        return True

    def _setChildren(self, children):

        self._roots = children

    def setDirty(self, dirty):

        if dirty:
            if not self._status & RepositoryView.LOADING:
                self._status |= CItem.CDIRTY
        else:
            self._status &= ~CItem.CDIRTY

    def isDirty(self):

        return self._status & CItem.CDIRTY != 0

    def isDirtyAgain(self):
        """
        Tell if changes were made since last time L{mapChanges} was called.
        """

        return self._status & CItem.FDIRTY != 0

    def closeView(self):
        """
        Close this repository view.

        All items in the view are marked stale. The item cache is flushed.
        A closed view cannot be used until is re-opened with L{openView}.
        """

        if not self._status & RepositoryView.OPEN:
            raise RepositoryError, "RepositoryView is not open"

        repository = self.repository
        if repository is not None:
            repository._openViews.remove(self)

        self.cancelQueuedNotifications()
        self._clear()

        if repository is not None:
            repository.store.detachView(self)

        self._status &= ~RepositoryView.OPEN

    def _clear(self):

        if self._registry:
            for item in self._registry.values():
                if hasattr(type(item), 'onViewClear'):
                    item.onViewClear(self)
                item._unloadItem(False, self, False)
            del item

        self._registry.clear()
        self._roots.clear()
        self._deletedRegistry.clear()
        self._instanceRegistry.clear()
        self._loadingRegistry.clear()

        if self._monitors:
            self._monitors.clear()
            self.MONITORING = False
        if self._watchers:
            self._watchers.clear()

        # clear other caches that may have been added upstream
        self.__dict__.clear()
        gc.collect()

    def prune(self, size):
        """
        Remove least-used items from the view's item cache.

        If there are C{size + 10%} items in the view's cache, the least-used
        items are removed from cache such that the cache size decreases to
        C{size - 10%} items.

        Pinned items and schema items are never removed from cache.
        
        @param size: the threshhold value
        @type size: integer
        """

        pass

    def walk(self, path, callable, _index=0, **kwds):
        """
        Walk a path and invoke a callable along the way.

        The callable's arguments need to be defined as C{parent},
        C{childName}, C{child} and C{**kwds}.
        The callable is passed C{None} for the C{child} argument if C{path}
        doesn't correspond to an existing item.
        The callable's return value is used to recursively continue walking
        when it is not C{None}.
        The callable may be C{None} in which case it is equivalent to:

            - C{lambda parent, name, child, **kwds: child}

        A C{load} keyword can be used to prevent loading of items by setting
        it to C{False}. Items are loaded as needed by default.

        @param path: an item path
        @type path: a L{Path<chandlerdb.util.Path.Path>} instance
        @param callable: a function, method, lambda body, or None
        @type callable: a python callable
        @param kwds: optional keywords passed to the callable
        @return: the item the walk finished on or C{None}
        """

        l = len(path)
        if l == 0:
            return None

        if path[_index] == '//':
            _index += 1

        if _index >= l:
            return None

        name = path[_index]
        if isinstance(name, UUID):
            root = self.findUUID(name, kwds.get('load', True))
            if root is not None and root.itsParent is not self:
                root = None
        else:
            root = self.getRoot(name, kwds.get('load', True))
        
        if callable is not None:
            root = callable(self, path[_index], root, **kwds)
        if root is not None:
            if _index == l - 1:
                return root
            return root.walk(path, callable, _index + 1, **kwds)

        return None

    def _fwalk(self, path, load=True):

        if not isinstance(path, Path):
            raise TypeError, '%s is not Path or UUID' %(type(path))

        item = self
        for name in path:

            if name == '//':
                item = self
            elif name == '/':
                item = item.itsRoot
            elif name == '..':
                item = item.itsParent
            elif name == '.':
                pass
            elif isinstance(name, UUID):
                child = self.find(name, load)
                if child is None or child.itsParent is not item:
                    item = None
                else:
                    item = child
            else:
                item = item.getItemChild(name, load)

            if item is None:
                break

        return item

    def findPath(self, path, load=True):
        """
        Find an item by path.

        See L{find} for more information.

        @param path: a path
        @type path: L{Path<chandlerdb.util.Path.Path>} or a path string
        @param load: load the item if it not yet loaded, C{True} by default
        @type load: boolean
        @return: an item or C{None} if not found
        """

        if isinstance(path, (str, unicode)):
            path = Path(path)
        elif not isinstance(path, Path):
            raise TypeError, '%s is not Path or string' %(type(path))

        return self._fwalk(path, load)

    def findUUID(self, uuid, load=True):
        """
        Find an item by UUID.

        See L{find} for more information.

        @param uuid: a UUID
        @type uuid: L{UUID<chandlerdb.util.c.UUID>} or a uuid string
        @param load: load the item if it not yet loaded, C{True} by default
        @type load: boolean
        @return: an item or C{None} if not found
        """

        if isinstance(uuid, (str, unicode)):
            uuid = UUID(uuid)
        elif not isinstance(uuid, UUID):
            raise TypeError, '%s is not UUID or string' %(type(uuid))

        return self.find(uuid, load)

    def findValue(self, uItem, name, default=Default, version=None):
        """
        Find a value for an item attribute.

        If the item is already loaded, regular attribute value retrieval is
        used.

        If the item is not loaded, only the value for the named attribute is
        returned with the following limitations:

            - only local values are returned, schema-based inheritance is
              not used to return a non-local value.

            - item references are returned as UUIDs, they are not actually 
              loaded.

            - bi-directional ref collections are returned read-only

        If the item does not exist or does not have a value for the given
        attribute the optional default value is returned or an exception is
        raised.

        To load multiple values for the same item, consider using
        L{findValues}.

        @param uItem: an item UUID
        @param name: an attribute name
        @param default: an optional default value to return if the item does
        not exist or does not have a local value for C{name}; an exception
        is raised if default is not specified and no value was found.
        @return: an attribute value or C{default}
        """

        if version is None:
            version = self.itsVersion

        if isuuid(uItem):
            item = self.find(uItem, False)
        else:
            item = uItem

        if item is not None and item.itsVersion <= version:
            return item.getLocalAttributeValue(name, default)

        reader, uValue = self.repository.store.loadValue(self, version,
                                                         uItem, name)
        if reader is None:
            if uValue is Nil:
                if default is Default:
                    raise KeyError, uItem
                return default
            if uValue is Default:
                if default is Default:
                    raise AttributeError, (uItem, name)
                return default

        return reader.readValue(self, uValue)[1]

    def hasValue(self, uItem, name):
        """
        Tell if an item has a local attribute value without loading it.

        As with L{findValue} and L{findValues}, if the item is already
        loaded, regular attribute retrieval is used.

        If the item is not loaded, the item record in the repository is
        checked for a value but it is not returned.

        @param uItem: an item UUID
        @param name: an attribute name
        @return: C{True} if a value was found, C{False} otherwise
        """

        item = self.find(uItem, False)
        if item is not None:
            return hasattr(item, name)

        return self.repository.store.hasValue(self, self.itsVersion,
                                              uItem, name)

    def hasTrueValue(self, uItem, name, version=None):
        """
        Find a value for an item attribute and check if it's 'True'.

        If the item is already loaded, regular attribute value retrieval is
        used.

        If the item is not loaded, only the value for the named attribute is
        returned with the following limitation:

            - only local values are tested, schema-based inheritance is
              not used to return a non-local value.

        If the item does not exist or does not have a value for the given
        attribute C{False} is returned.

        @param uItem: an item UUID
        @param name: an attribute name
        @return: C{True} or C{False}
        """

        if version is None:
            version = self.itsVersion

        item = self.find(uItem, False)
        if item is not None and item.itsVersion <= version:
            return item.hasTrueAttributeValue(name)

        reader, uValue = self.repository.store.loadValue(self, version,
                                                         uItem, name)
        if reader is None:
            return False

        return reader.hasTrueValue(self, uValue)

    def hasTrueValues(self, uItem, *names):
        """
        Find values for attributes of an item and check if they are 'True'.

        As with L{findValues}, if the item is already loaded, regular
        attribute value retrieval is used.

        If the item is not loaded, the values for the named attributes are
        checked, without loading the item, with the following limitations:

            - only local values are returned, schema-based inheritance is
              not used to return a non-local value.

        If the item does not exist or does not have a value for the given
        attribute False is returned.

        @param uItem: an item UUID
        @param names: one or more name for each attribute to check.
        @return: C{True} if all values are True, C{False} otherwise.
        """

        item = self.find(uItem, False)
        if item is not None:
            for name in names:
                if not item.hasTrueAttributeValue(name):
                    return False
            return True

        reader, uValues = self.repository.store.loadValues(self,
                                                           self.itsVersion,
                                                           uItem, names)
        if reader is None or None in uValues:
            return False

        for uValue in uValues:
            if not reader.hasTrueValue(self, uValue):
                return False

        return True

    def _findKind(self, spec, withSchema):

        return self.find(spec)

    def getACL(self, uuid, name, default=None):
        """
        Get an Access Control List.

        ACLs are stored by C{(uuid, name)} tuples. C{name} can be C{None}.
        Therefore, each item in the repository may have an ACL, and each
        attribute value for each item in the repository may also have an
        ACL.

        By convention, the ACL for an item is stored with C{(item.itsUUID,
        None)} and the ACL for an attribute value on an item is stored with
        C{(item.itsUUID, attributeName)}.

        @param uuid: a L{UUID<chandlerdb.util.c.UUID>} instance
        @param name: a string or C{None}
        @param default: an optional default value to return when no ACL is
        found (by default C{None} is returned)
        @return: an L{ACL<chandlerdb.item.Access.ACL>} instance or C{None}
        """

        acl = self.repository.store.loadACL(self, self._version, uuid, name)
        if acl is None:
            return default

        return acl

    def loadPack(self, path, parent=None, package=None):
        """
        Load items from the pack definition file at path.

        This is mostly a bootstrap feature.

        @param path: the path to the packfile to load
        @type path: a string
        @param parent: the item to load the items in the pack under
        @type parent: an item
        @param package: the name of the package to extract the pack from as
                        a resource via setuptools' pkg_resources API.
        @type package: a string
        @return: the loaded pack, an item of kind Pack
        """

        from chandlerdb.persistence.PackHandler import PackHandler

        handler = PackHandler(path, parent, package, self)

        try:
            verify = self._setVerify(False)
            if package is not None:
                if os.path.sep != '/':
                    path = path.replace(os.path.sep, '/')
                stream = resource_stream(package, path)
            else:
                stream = None
            handler.parseFile(path, stream)
        finally:
            self._setVerify(verify)

        return handler.pack

    def dir(self, item=None, path=None):
        """
        Print out a listing of each item in the repository or under item.

        This is a debugging feature.

        @param item: the item to list children of, or C{None}
        @type item: an item
        @param path: the path to the item to list children of, or C{None}
        @type path: a L{Path<chandlerdb.util.Path.Path>} instance
        """
        
        if item is None:
            path = Path('//')
            for root in self.iterRoots():
                self.dir(root, path)
        else:
            if path is None:
                path = item.itsPath
            else:
                path.append(item._name or item._uuid)
            print path
            for child in item.iterChildren():
                self.dir(child, path)
            path.pop()

    def check(self, repair=False):
        """
        Runs repository consistency checks on this view.

        All items of the repository are loaded into this view and checked
        for consistency with their schema definition. See
        L{Item.check<chandlerdb.item.Item.Item.check>} for more details.
        """

        result = True
        for root in list(self.iterRoots()):
            check = root.check(True, repair)
            result = result and check

        return result

    def hasRoots(self):
        """
        Tell whether this view has any roots.

        @return: C{True} or C{False}
        """

        return (self._roots is not None and
                self._roots._firstKey is not None)

    def hasRoot(self, name, load=True):
        """
        Tell whether the repository has a root by a given name.

        This view is searched for a root.

        @param name: the name of the root to be looked for
        @type name: a string
        @param load: controls whether to check only loaded roots if
        C{False} or all roots if C{True}, the default.
        @return: C{True} or C{False}
        """

        return (name is not None and
                self._roots.resolveAlias(name, load) is not None)

    def getRoot(self, name, load=True):
        """
        Get a root by a given name.

        This view is searched for a root.

        @param name: the name of the root to be looked for
        @type name: a string
        @param load: controls whether to check only loaded roots if
        C{False} or all roots if C{True}, the default.
        @return: a root item or C{None} if not found.
        """

        return self._roots.getByAlias(name, None, load)

    def getItemChild(self, name, load=True):

        return self.getRoot(name, load)

    def hasChildren(self):

        return self.hasRoots()

    def hasChild(self, name, load=True):

        return self.hasRoot(name, load)

    def __iter__(self):
        """
        (deprecated) Use L{iterRoots} instead.
        """

        raise DeprecationWarning, 'Use RepositoryView.iterRoots() instead'
    
    def iterChildren(self):
        """
        See L{iterRoots}
        """

        return self.iterRoots()
    
    def iterRoots(self, load=True):
        """
        Iterate over the roots of this repository in this view.
        """

        if not load:
            for child in self._roots._itervalues():
                yield child._value

        else:
            for child in self._roots:
                yield child

    def _getPath(self, path=None):

        if path is None:
            path = Path()
        path.set('//')

        return path

    def _getStore(self):

        return self.repository.store

    def _logItem(self, item):

        if not self.repository.isOpen():
            raise RepositoryError, 'Repository is not open'

        if item.itsView is not self:
            raise RepositoryError, 'Repository view is not owning item: %s' %(item.itsPath)

        return not self.isLoading()

    def dirtyItems(self):

        raise NotImplementedError, "%s.dirtyItems" %(type(self))

    def hasDirtyItems(self):

        raise NotImplementedError, "%s.hasDirtyItems" %(type(self))

    def _addItem(self, item):

        name = item.itsName
        if name is not None:
            key = self._roots.resolveAlias(name, not self.isLoading())
            if not (key is None or key == item.itsUUID):
                raise ValueError, "A root named '%s' exists already" %(name)

        self._roots._append(item)

        return item

    def _removeItem(self, item):

        del self._roots[item.itsUUID]

    def refresh(self, mergeFn=None, version=None, notify=True):
        """
        Refresh this view to the changes made in other views.

        Refreshing a view causes the following to happen, in this order:
        
            1. Version conflicts are detected. If an item in this view was
               changed in another view and it committed its changes first,
               there is a chance that these changes would conflict with the
               ones about to be committed by this view. A
               C{VersionConflictError} is raised in that situation.
            2. The view is refreshed to the latest version in persistent
               store. Pointers to items that changed in other views that are
               also in this view are marked C{STALE} unless they're pinned
               in memory in which case they're refreshed in place.
            3. Change and history notifications from changes in other views
               are dispatched after the merges succeeded if C{notify} is
               C{True}, the default.
            4. If the view's cache has reached a threshhold item count - at
               the moment 10,000 - the least-used items are removed from
               cache and pointers to them are marked C{STALE} such that the
               size of the cache drops below 90% of this threshhold.
        """
        
        raise NotImplementedError, "%s.refresh" %(type(self))

    def commit(self, mergeFn=None, notify=True, afterCommit=None):
        """
        Commit all the changes made to items in this view.

        Committing a view causes the following to happen, in this order:
        
            1. L{refresh} is called.
            2. All changes made to items in the view are saved to
               persistent storage.
            3. Change and history notifications from the items committed
               are dispatched after the transactions commits if C{notify} is
               {True}, the default.
            4. After commit is completely done, C{afterCommit} is called if
               found to be callable.
        """
        
        raise NotImplementedError, "%s.commit" %(type(self))

    def cancel(self):
        """
        Cancel all the changes made to items in this view.

        Cancelling a view causes the following to happen, in this order:
        
            1. All new items are unloaded.
            2. All deleted and changed items are refreshed to their original
               state and marked unchanged.
            3. If the view's cache has reached a threshhold item count - at
               the moment 10,000 - the least-used items are removed from
               cache and pointers to them are marked C{STALE} such that the
               size of the cache drops below 90% of this threshhold.
        """
        
        raise NotImplementedError, "%s.cancel" %(type(self))

    def queryItems(self, kind=None, attribute=None):
        """
        Query this view for items.

        @param kind: a kind item for a kind query
        @type kind: an item
        @param attribute: an attribute UUID for a value query
        @type attribute: a UUID
        """
        
        raise NotImplementedError, "%s.queryItems" %(type(self))

    def queryItemKeys(self, kind=None, attribute=None):
        """
        Query this view for item UUIDs.

        @param kind: a kind item for a kind query
        @type kind: an item
        @param attribute: an attribute UUID for a value query
        @type attribute: a UUID
        """
        
        raise NotImplementedError, "%s.queryItemKeys" %(type(self))

    def kindForKey(self, uuid):

        raise NotImplementedError, "%s.kindForKey" %(type(self))

    def searchItems(self, query, attribute=None, load=True):
        """
        Search this view for items using an Lucene full text query.

        All matches are returned. This method is a generator, iteration may
        be stopped before all matches are instantiated.

        @param query: a lucene query
        @type query: a string
        @param attribute: an attribute name to match against, C{None} by
        default to match against all attributes.
        @type attribute: a string
        @param load: if C{False} only return loaded items
        @type load: boolean
        """

        if attribute is not None:
            uAttr = attribute.itsUUID
        else:
            uAttr = None

        for uItem, uAttr in self.store.searchItems(self, query, uAttr):
            item = self.find(uItem, load)
            if item is not None:
                yield item, self[uAttr].itsName

    def _loadItem(self, uuid):
        raise NotImplementedError, "%s._loadItem" %(type(self))

    def _loadRoot(self, name):
        raise NotImplementedError, "%s._loadRoot" %(type(self))

    def mapChanges(self, freshOnly=False):
        """
        Generate a change tuple for every item changed in this view.

        For each item that was changed in this view since it was last
        committed a tuple is generated with the following elements:

            - the item

            - the item's current version

            - the item's current status bits

            - a list of changed literal attribute names

            - a list of changed references attribute names

        @param freshOnly: optionally limit tuple generation to items that
                          were changed since last time this method was
                          called or since the last commit, whichever came
                          last; C{False} by default.
        @type freshOnly: boolean
        """

        raise NotImplementedError, "%s.mapChanges" %(type(self))
    
    def mapChangedItems(self, freshOnly=False):
        """
        Yield every item changed in this view.

        @param freshOnly: optionally yield only items that were changed
                          since last time this method was called or since
                          the last commit, whichever came last; C{False} by
                          default. 
        @type freshOnly: boolean
        """

        raise NotImplementedError, "%s.mapChanges" %(type(self))
    
    def mapHistory(self, fromVersion=-1, toVersion=0, history=None):
        """
        Generate a change tuple for every committed item change in other views.

        For each item that was changed and committed in another view a
        a tuple is generated with the following elements:

            - the UUID of the item

            - the item's committed version for the change

            - the item's Kind item

            - the item's committed status bits for the change

            - a list of changed literal attribute names

            - a list of changed references attribute names

            - None or the item's previous kind if it changed

        @param fromVersion: the version to start iterating changes from, the
        current version by default.
        @type fromVersion: integer
        @param toVersion: the version to continue iterating changes to, the
        latest committed version by default.
        @type toVersion: integer
        @param history: instead of querying the repository history between
        versions, use the history records in this list.
        @type history: iterable
        """

        raise NotImplementedError, "%s.mapHistory" %(type(self))

    def mapHistoryKeys(self, fromVersion=-1, toVersion=0):
        """
        Generate a change tuple for every committed item change in other views.

        For each item that was changed and committed in another view a
        a tuple is generated with the following elements:

            - the UUID of the item

            - the item's committed version for the change

        @param fromVersion: the version to start iterating changes from, the
        current version by default.
        @type fromVersion: integer
        @param toVersion: the version to continue iterating changes to, the
        latest committed version by default.
        @type toVersion: integer
        """

        raise NotImplementedError, "%s.mapHistoryKeys" %(type(self))

    def getItemVersion(self, version, item):

        return self.repository.store.getItemVersion(self, version, item.itsUUID)

    def queueNotification(self, item, op, change, name, other, dirties):

        self._queuedNotifications.put((item.itsUUID, op, change, name,
                                       other, dirties))

    def dispatchQueuedNotifications(self):
        """
        Dispatch queued notifications until queue is empty.

        Changes to items changed since last time this method was called are
        also dispatched, potentially refilling the notification queue.
        """
        count = 0
        queue = self._queuedNotifications

        while True:
            while not queue.empty():
                uItem, op, change, name, other, dirties = queue.get()
                count += 1

                watchers = self._watchers.get(uItem)
                if watchers:
                    watchers = watchers.get(self.SUBSCRIBERS)
                    if watchers:
                        try:
                            collection = self[uItem]
                        except KeyError:
                            continue
                        else:
                            for watcher in watchers:
                                watcher(op, change, collection, name,
                                        other, dirties)

            while self.isDirtyAgain():
                self.dispatchChanges(self.mapChangedItems(True))

            if queue.empty():
                break

        return count

    def cancelQueuedNotifications(self):
        """
        Clear the notification queue, not dispatching the queued notifications.
        """
        count = 0
        queue = self._queuedNotifications

        while not queue.empty():
            queue.get()
            count += 1

        return count

    def dispatchChanges(self, items, dirties=()):
        """
        Notify kind extents and collection watchers that items have changed.

        The extents of the changed items' kinds and superkinds notified.

        The collection watchers watching ref collection attributes on the
        changed items that have their C{notify} aspect set are invoked. This
        ensures that these collections are notified about the changed items
        they contain.

        Calling this method is not normally necessary as it is called during
        L{refresh} on the currently dirty items for which it hasn't been
        called yet.

        @param items: an iterable of items that changed, to be iterated once.
        """
        version = self.itsVersion

        for item in items:
            kind = item.itsKind

            if kind is not None:

                if item.isDirty():
                    _dirties = item.itsValues._getDirties(True)
                    _dirties.extend(item.itsRefs._getDirties(True))
                else:
                    _dirties = ()

                if dirties:
                    if _dirties:
                        _dirties = dirties + tuple(_dirties)
                    else:
                        _dirties = dirties
                elif _dirties:
                    _dirties = tuple(_dirties)
                else:
                    continue

                uItem = item.itsUUID
                kind.extent._collectionChanged('changed', 'notification',
                                               'extent', uItem, _dirties)

                for name in kind._iterNotifyAttributes():
                    value = getattr(item, name, None)
                    if isinstance(value, RefList):
                        otherName = value._otherName
                        for uRef in value.iterkeys():
                            watchers = self.findValue(uRef, 'watchers', None,
                                                      version)
                            if watchers:
                                watchers = watchers.get(otherName, None)
                                if watchers:
                                    for watcher in watchers:
                                        if watcher is not None:
                                            watcher('changed', 'notification',
                                                    uRef, otherName,
                                                    uItem, _dirties)

    def _dispatchHistory(self, history, refreshes, oldVersion, newVersion):

        raise NotImplementedError, "%s._dispatchHistory" %(type(self))

    def _dispatchChanges(self, changes):

        raise NotImplementedError, "%s._dispatchChanges" %(type(self))

    def _registerWatch(self, watchingItem, watchedItem, cls, key, *args):

        uWatching = watchingItem.itsUUID
        uWatched = watchedItem.itsUUID

        watchers = self._watchers.get(uWatched)
        if watchers is None:
            self._watchers[uWatched] = {key: [cls(self, uWatching, *args)]}
        else:
            watchers = watchers.get(key)
            if watchers is None:
                self._watchers[uWatched][key] = [cls(self, uWatching, *args)]
            else:
                for watcher in watchers:
                    if (watcher.watchingItem == uWatching and
                        type(watcher) is cls and watcher.compare(*args)):
                        return watcher
                watchers.append(cls(self, uWatching, *args))
                
        if cls is TransientWatchItem:
            watchedItem._status |= CItem.T_WATCHED

        return self._watchers[uWatched][key][-1]

    def _unregisterWatch(self, watchingItem, watchedItem, cls, key, *args):

        watchers = self._watchers
        uWatching = watchingItem.itsUUID
        uWatched = watchedItem.itsUUID

        if watchers:
            watchers = watchers.get(uWatched)
            if watchers:
                watchers = watchers.get(key)
                if watchers:
                    for watcher in watchers:
                        if (watcher.watchingItem == uWatching and
                            type(watcher) is cls and watcher.compare(*args)):
                            watchers.remove(watcher)
                    if not watchers:
                        del self._watchers[uWatched][key]
                        if not self._watchers[uWatched]:
                            del self._watchers[uWatched]
                        if cls is TransientWatchItem:
                            watchedItem._status &= ~CItem.T_WATCHED

    def _unregisterWatches(self, item):

        watchers = self._watchers
        if watchers:
            uItem = item.itsUUID
            watchers.pop(uItem, None)
            for uWatched, watcherDict in watchers.items():
                for key, watchers in watcherDict.items():
                    watchers = [watcher for watcher in watchers
                                if watcher.watchingItem != uItem]
                    if watchers:
                        watcherDict[key] = watchers
                    else:
                        del watcherDict[key]
                if not watcherDict:
                    del self._watchers[uWatched]

    def watchItem(self, watchingItem, watchedItem, methodName):
        return self._registerWatch(watchingItem, watchedItem,
                                   TransientWatchItem,
                                   watchedItem.itsUUID, methodName)

    def unwatchItem(self, watchingItem, watchedItem, methodName):
        self._unregisterWatch(watchingItem, watchedItem, TransientWatchItem,
                              watchedItem.itsUUID, methodName)

    def watchKind(self, watchingItem, kind, methodName):
        return self._registerWatch(watchingItem, kind.extent,
                                   TransientWatchKind,
                                   'extent', methodName)

    def unwatchKind(self, watchingItem, kind, methodName):
        self._unregisterWatch(watchingItem, kind.extent, TransientWatchKind,
                              'extent', methodName)

    def watchCollection(self, watchingItem, owner, attribute, methodName):
        return self._registerWatch(watchingItem, owner,
                                   TransientWatchCollection,
                                   attribute, methodName)

    def unwatchCollection(self, watchingItem, owner, attribute, methodName):
        self._unregisterWatch(watchingItem, owner, TransientWatchCollection,
                              attribute, methodName)

    def watchCollectionQueue(self, watchingItem, collection, methodName):
        return self._registerWatch(watchingItem, collection,
                                   TransientWatchCollection,
                                   RepositoryView.SUBSCRIBERS, methodName)

    def unwatchCollectionQueue(self, watchingItem, collection, methodName):
        self._unregisterWatch(watchingItem, collection,
                              TransientWatchCollection,
                              RepositoryView.SUBSCRIBERS, methodName)

    def printVersions(self, fromVersion=1, toVersion=0):

        for version, (then, viewSize, commitCount, name) in self.store.iterCommits(self, fromVersion, toVersion):
            if name == self.name:
                then = time.strftime("%d-%b-%y,%H:%M:%S", time.localtime(then))
                print "%6d: %s %4d %4d" %(version, then,
                                          viewSize, commitCount)

    def printItemVersions(self, item, fromVersion=1, toVersion=0):

        store = self.store
        for version, status in store.iterItemVersions(self, item.itsUUID, fromVersion, toVersion):
            then, viewSize, commitCount, name = store.getCommit(version)
            if name == self.name:
                then = time.strftime("%d-%b-%y,%H:%M:%S", time.localtime(then))
                print "%6d: %s %4d %4d 0x%08x" %(version, then,
                                                 viewSize, commitCount, status)

    def printItemChanges(self, item, fromVersion=1, toVersion=0):

        store = self.store
        prevValues = set()
        prevNames = set()

        if fromVersion > 1:
            for version, status in store.iterItemVersions(self, item.itsUUID, fromVersion - 1, 0, True):
                then, viewSize, commitCount, name = store.getCommit(version)
                reader, uValues = store.loadValues(self, version, item.itsUUID)
                prevValues = set(uValues)
                prevNames = set(store.loadItemName(self, version, uAttr)
                                for uAttr in (reader.readAttribute(self, uValue)
                                              for uValue in uValues))
                break
                
        for version, status in store.iterItemVersions(self, item.itsUUID, fromVersion, toVersion):
            then, viewSize, commitCount, name = store.getCommit(version)
            reader, uValues = store.loadValues(self, version, item.itsUUID)
            currValues = set(uValues)
            currNames = set(store.loadItemName(self, version, uAttr)
                            for uAttr in (reader.readAttribute(self, uValue)
                                          for uValue in uValues))
            if name == self.name:
                # removed values not included
                names = [store.loadItemName(self, version, uAttr)
                         for uAttr in (reader.readAttribute(self, uValue)
                                       for uValue in currValues - prevValues)]
                print "%6d 0x%08x %s:" %(version, status, name)
                print "      changed: %s" %(', '.join(sorted(names)))
                print "      removed: %s" %(', '.join(sorted(prevNames -
                                                             currNames)))
            prevValues = currValues
            prevNames = currNames

    def printCurrentChanges(self, detailed=False):

        kinds = {}
        for item in self.dirtyItems():
            kind = item.itsKind
            if kind in kinds:
                kinds[kind].append(item)
            else:
                kinds[kind] = [item]

        changes = kinds.items()
        changes.sort(key=lambda x: len(x[1]), reverse=True)

        for kind, items in changes:
            print kind, len(items)

        if detailed:
            for kind, items in changes:
                print kind
                for item in items:
                    print '  ', item._repr_(), ', '.join(item.iterAttributeNames(changedOnly=True))

    def reindex(self, items, *attributes):
        """
        Reindex items in attribute-sorted indexes in bulk.

        Normally, reindexing is triggered when attributes change by the
        monitors watching them. This method should only be used in special
        circumstances where a change outside of attributes could have an
        effect on the indexing of items.

        For example, in Chandler, when the current timezone changes, all
        floating events need to be reindexed via this API as the timezone
        change is not detected by a change in attributes.
        """
        
        if not self.MONITORING:
            self.getSingleton(self.MONITORS).cacheMonitors()
        
        monitors = self._monitors.get('set')
        if monitors:
            with self.reindexingDeferred():
                for item in items:
                    for attribute in attributes:
                        for monitor in monitors.get(attribute, Nil):
                            monitor('set', item, attribute)

    def _updateIndexes(self, newIndexes, items):
        
        map = {}
        for uItem, attr, name in newIndexes:
            item = self.find(uItem)
            if item is not None and item.isLive():
                indexed = getattr(item, attr, None)
                if isinstance(indexed, Indexed):
                    if indexed.hasIndex(name):
                        index = indexed.getIndex(name)
                        if isinstance(index, SortedIndex):
                            index.validateIndex(False)
                        if indexed in map:
                            map[indexed].append(index)
                        else:
                            map[indexed] = [index]

        for item in items:
            uItem = item.itsUUID
            for indexed, indexes in map.iteritems():
                anIndex = indexed._anIndex(indexes)
                if anIndex is not None:
                    if uItem in anIndex:
                        for index in indexes:
                            index.moveKey(uItem, Default, True)
                    else:
                        for index in indexes:
                            index.removeKey(uItem)
                elif indexed.__contains__(item, False, True):
                    for index in indexes:
                        index.moveKey(uItem, Default, True)
                else:
                    for index in indexes:
                        index.removeKey(uItem)

        for indexes in map.itervalues():
            for index in indexes:
                if not index.isValid():
                    index.validateIndex(True, True)

        for indexed, indexes in map.iteritems():
            for index in indexes:
                if index._changedKeys:
                    indexed._setDirty(True)
                    break


    itsUUID = UUID('3631147e-e58d-11d7-d3c2-000393db837c')
    SUBSCRIBERS = UUID('4dc81eae-1689-11db-a0ac-0016cbc90838')

    itsPath = property(_getPath)
    views = property(lambda self: self.repository.getOpenViews())


class OnDemandRepositoryView(RepositoryView):

    def __init__(self, repository, name=None, version=None,
                 deferDelete=Default, pruneSize=Default, notify=Default,
                 mergeFn=None, timezone=Default, ontzchange=None):

        if version is None:
            version = repository.store.getVersion()

        super(OnDemandRepositoryView, self).__init__(repository, name, version,
                                                     deferDelete, pruneSize,
                                                     notify, mergeFn, timezone,
                                                     ontzchange)

    def openView(self, version=None, deferDelete=Default, notify=Default,
                 mergeFn=None, timezone=Default, ontzchange=None):

        self._exclusive = threading.RLock()
        self._hooks = []
        
        super(OnDemandRepositoryView, self).openView(version, deferDelete,
                                                     notify, mergeFn,
                                                     timezone, ontzchange)

    def isNew(self):

        return self.itsVersion == 0

    def _acquireExclusive(self):

        return self._exclusive.acquire()

    def _releaseExclusive(self):

        return self._exclusive.release()

    def _setLoading(self, loading, runHooks=False):

        try:
            if not loading and runHooks and self.isLoading():
                try:
                    for hook in self._hooks:
                        hook(self)
                finally:
                    self._hooks = []
        finally:
            return super(OnDemandRepositoryView, self)._setLoading(loading)

    def _readItem(self, itemReader):

        release = False
        try:
            loading = self.isLoading()
            if not loading:
                release = self._acquireExclusive()
                self._setLoading(True)
                self._hooks = []

            item = itemReader.readItem(self, self._hooks)
        except:
            if not loading:
                self._setLoading(False, False)
                self._hooks = []
            raise
        else:
            if not loading:
                self._setLoading(False, True)

            return item
        finally:
            if release:
                self._releaseExclusive()

    def _loadItem(self, uuid):

        if not uuid in self._deletedRegistry:
            current = threading.currentThread()

            thread = self._loadingRegistry.get(uuid)
            if thread is not None:
                if thread is current:
                    raise RecursiveLoadItemError, uuid
                raise ConcurrentLoadItemError, (uuid, thread, current)

            itemReader = self.repository.store.loadItem(self, self.itsVersion,
                                                        uuid)
            if itemReader is not None:
                try:
                    self._loadingRegistry[uuid] = current
                    return self._readItem(itemReader)
                finally:
                    del self._loadingRegistry[uuid]

        return None

    def _findSchema(self, spec, withSchema):

        if withSchema:
            return self.find(spec, False)

        # when crossing the schema boundary, reset loading status so that
        # hooks get called before resuming regular loading

        try:
            hooks = self._hooks
            loading = self._setLoading(False)
            
            return self.find(spec)
        finally:
            self._hooks = hooks
            self._setLoading(loading)

    def _addItem(self, item):

        super(OnDemandRepositoryView, self)._addItem(item)

        item.setPinned(True)

        return item

    def _removeItem(self, item):

        super(OnDemandRepositoryView, self)._removeItem(item)

        item.setPinned(False)
        
    def prune(self, size):

        registry = self._registry
        viewSize = len(registry)

        if viewSize > size * 1.2:
            gc.collect()
            heap = [(item._lastAccess, item.itsUUID)
                    for item in registry.itervalues()
                    if not item.itsStatus & (item.PINNED | item.DIRTY)]
            heapSize = len(heap)
            heapify(heap)

            count = viewSize - int(size * 0.8)
            if count > 0:
                debug = self.isDebug()

                if self.isRefCounted():
                    for i in xrange(heapSize):
                        item = registry[heappop(heap)[1]]
                        pythonRefs = sys.getrefcount(item)
                        if pythonRefs <= 3:
                            item._unloadItem(False, self)
                            count -= 1
                            if count == 0:
                                break
                        elif debug:
                            self.logger.debug('not pruning %s (refCount %d)',
                                              item._repr_(), pythonRefs)
                else:
                    for i in xrange(count):
                        registry[heappop(heap)[1]]._unloadItem(False, self)

                gc.collect()
                self.logger.info('%s pruned to %d items', self, len(registry))


class NullRepositoryView(RepositoryView):

    def __init__(self, name=None, verify=False, timezone=Default,
                 ontzchange=None):

        super(NullRepositoryView, self).__init__(None,
                                                 name=name,
                                                 timezone=timezone,
                                                 ontzchange=ontzchange)

        if verify:
            self._status |= RepositoryView.VERIFY

    def openView(self, version=None, deferDelete=Default, notify=Default,
                 mergeFn=None, timezone=Default, ontzchange=None):

        self._logger = logging.getLogger(__name__)
        super(NullRepositoryView, self).openView(version=0,
                                                 deferDelete=False,
                                                 notify=False,
                                                 timezone=timezone,
                                                 ontzchange=ontzchange)

    def _loadTimezone(self):

        return None

    def refresh(self, mergeFn=None):
        
        raise AssertionError, "Null view cannot refresh"

    def commit(self, mergeFn=None):
        
        raise AssertionError, "Null view cannot commit"

    def cancel(self):
        
        raise AssertionError, "Null view cannot cancel"

    def _createRefList(self, item, name, otherName, dictKey, 
                       readOnly, new, uuid):

        return NullViewRefList(self, item, name, otherName, dictKey, readOnly)
    
    def _createChildren(self, parent, new):

        return Children(self, parent, new)

    def _createNumericIndex(self, **kwds):

        return NumericIndex(**kwds)
    
    def _getLobType(self):

        return NullViewLob

    def _findSchema(self, spec, withSchema):

        return self.find(spec, False)

    def _loadItem(self, uuid):

        return None

    def findValue(self, uItem, name, default=Default):

        if default is not Default:
            return getattr(self[uItem], name, default)

        return getattr(self[uItem], name)

    def setDirty(self, dirty):

        pass

    def isDirty(self):

        return False

    def isOpen(self):

        return (self._status & RepositoryView.OPEN) != 0

    def isNew(self):

        return False

    def isStale(self):

        return False

    def isRefCounted(self):

        return True
        
    def isLoading(self):

        return False

    def isDebug(self):

        return self._logger.getEffectiveLevel() <= logging.DEBUG

    def _isNullView(self):

        return True

    def _setLoading(self, loading, runHooks=False):

        raise AssertionError, "Null view cannot load items"

    def _getStore(self):

        return None

    def mapChanges(self, callable, freshOnly=False):

        pass

    def _logItem(self, item):

        return True

    def dirtyItems(self):

        return self._registry.itervalues()

    def hasDirtyItems(self):

        return len(self._registry) > 0

    def getLogger(self):

        return self._logger

    def getItemVersion(self, version, item):

        return item._version

    def queryItems(self, kind=None, attribute=None):

        if kind is not None:
            return (item for item in self._registry.itervalues()
                    if item._kind is kind)

        elif attribute is not None:
            raise NotImplementedError, 'attribute query'

        else:
            raise ValueError, 'one of kind or value must be set'

    def queryItemKeys(self, kind=None, attribute=None):

        if kind is not None:
            return (key for key, item in self._registry.iteritems()
                    if item._kind is kind)

        elif attribute is not None:
            raise NotImplementedError, 'attribute query'

        else:
            raise ValueError, 'one of kind or value must be set'

    def kindForKey(self, uuid):

        return self[uuid].itsKind

    logger = property(getLogger)
    itsUUID = UUID('17368718-a164-11d9-9351-000393db837c')


class NullViewLob(Lob):

    def __init__(self, view, *args, **kwds):

        super(NullViewLob, self).__init__(*args, **kwds)


class NullViewRefList(RefList):

    def __init__(self, view, item, name, otherName, dictKey, readOnly):

        super(NullViewRefList, self).__init__(view, item, name, otherName,
                                              dictKey, readOnly, CLinkedMap.NEW)

    def _setOwner(self, item, name):

        super(NullViewRefList, self)._setOwner(item, name)
        if item is not None:
            self.view = item.itsView

    def linkChanged(self, link, key):
        pass
    
    def _check(self, logger, item, name, repair):
        return True

    def _load(self, key):
        return False
    
    def _setDirty(self, noFireChanges=False):
        pass

    def iterkeys(self, excludeIndexes=False, firstKey=None, lastKey=None):
        return super(NullViewRefList, self).iterkeys(firstKey, lastKey)

    def _unloadRef(self, item):

        key = item.itsUUID
        self._flags |= CLinkedMap.LOAD

        if self.has_key(key, False):
            self._get(key, False).value = key


class TransientWatch(object):
    
    def __init__(self, view, watchingItem):

        self.view = view
        self.watchingItem = watchingItem


class TransientWatchCollection(TransientWatch):

    def __init__(self, view, watchingItem, methodName):

        super(TransientWatchCollection, self).__init__(view, watchingItem)
        self.methodName = methodName
        
    def __call__(self, op, change, owner, name, other, dirties):

        try:
            watchingItem = self.view[self.watchingItem]
        except KeyError:
            return

        getattr(watchingItem, self.methodName)(op, owner, name, other, dirties)

    def compare(self, methodName):

        return self.methodName == methodName


class TransientWatchKind(TransientWatch):

    def __init__(self, view, watchingItem, methodName):

        super(TransientWatchKind, self).__init__(view, watchingItem)
        self.methodName = methodName
        
    def __call__(self, op, change, owner, name, other, dirties):

        try:
            watchingItem = self.view[self.watchingItem]
            if isuuid(owner):
                kind = self.view[owner].kind
            else:
                kind = owner.kind
        except KeyError:
            return

        getattr(watchingItem, self.methodName)(op, kind, other, dirties)

    def compare(self, methodName):

        return self.methodName == methodName


class TransientWatchItem(TransientWatch):

    def __init__(self, view, watchingItem, methodName):

        super(TransientWatchItem, self).__init__(view, watchingItem)
        self.methodName = methodName
        
    def __call__(self, op, uItem, dirties):

        try:
            watchingItem = self.view[self.watchingItem]
        except KeyError:
            return

        getattr(watchingItem, self.methodName)(op, uItem, dirties)

    def compare(self, methodName):

        return self.methodName == methodName


class ViewTZInfo(object):

    def __init__(self, view, default, ontzchange):

        if not default:
            default = ICUtzinfo.default
        elif not isinstance(default, ICUtzinfo):
            raise TypeError, default

        self.view = view
        self._default = default
        self._floating = FloatingTZ(self._default)
        self._ontzchange = ontzchange or Nil

        self.UTC = ICUtzinfo.getInstance('UTC')
        self.GMT = ICUtzinfo.getInstance('GMT')

    def getDefault(self):
        return self._default

    def getFloating(self):
        return self._floating

    def getInstance(self, name):
        if name == self._floating.tzid:
            return self._floating
        return ICUtzinfo.getInstance(name)

    def setDefault(self, default):
        if isinstance(default, FloatingTZ):
            raise TypeError, ("Floating timezone can't be default", default)
        elif not isinstance(default, ICUtzinfo):
            raise TypeError, default
        current = self._default
        if current != default:
            self._default = default
            self._floating.tzinfo = default
            self._ontzchange(self.view, default)
        return current

    def getOnTZChange(self):
        return self._ontzchange

    def setOnTZChange(self, ontzchange):
        self._ontzchange = ontzchange or Nil

    default = property(getDefault, setDefault)
    floating = property(getFloating)
    ontzchange = property(getOnTZChange, setOnTZChange)
