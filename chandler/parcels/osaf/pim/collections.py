#   Copyright (c) 2003-2006 Open Source Applications Foundation
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


__parcel__ = "osaf.pim"

from application import schema

from chandlerdb.util.c import Default, Nil
from repository.item.Sets import (
    Set, MultiUnion, Union, MultiIntersection, Intersection, Difference,
    KindSet, ExpressionFilteredSet, MethodFilteredSet, EmptySet
)
from repository.item.Collection import Collection

from osaf.pim.items import ContentItem
import itertools

# Common attribute for collection inclusions
inclusions = schema.Sequence(inverse=ContentItem.collections, initialValue=[])


class IndexDefinition(schema.Item):
    """
    A definition of an index, able to create an index on a collection (given the
    collection).

    Creates either of two kinds of indexes:
    - if useMaster, an index on the ContentItem kind collection will be created
      if one doesn't exist, and a subindex on the given collection will be
      created to point at it.
    - if not useMaster, a standalone index will be created.
    """
    useMaster = schema.One(schema.Boolean, defaultValue=True)

    attributes = schema.Sequence(schema.Text)

    def __init__(self, *args, **kwds):
        """
        When we construct an L{IndexDefinition}, we need to make sure
        it gets added to the L{IndexDefinitionCollection} that tracks
        them.
        """
        super(IndexDefinition, self).__init__(*args, **kwds)

        allDefs = schema.ns("osaf.pim", self.itsView).allIndexDefinitions
        allDefs.indexDefinitions.append(self, alias=self.itsName)

    @classmethod
    def makeIndexByName(cls, collection, indexName):
        """
        Find the IndexDefintion with this name and use it to create an index
        on this collection
        """
        allDefs = schema.ns("osaf.pim", collection.itsView).allIndexDefinitions
        key = allDefs.indexDefinitions.resolveAlias(indexName)
        indexDef = allDefs.indexDefinitions[key]
        indexDef.makeIndex(collection)

    def makeIndex(self, collection):
        """
        Create this index on this collection.
        """
        if self.useMaster:
            # Create the master index if it doesn't already exist.
            # For debugging, only index Notes by doing this instead (this won't
            # work for real because Certificates aren't Notes):
            # contentItems = schema.ns("osaf.pim", collection.itsView).noteCollection
            contentItems = schema.ns("osaf.pim", collection.itsView).contentItems
            if not contentItems.hasIndex(self.itsName):
                self.makeIndexOn(contentItems)

            # Create a subindex that inherits from the master
            collection.addIndex(self.itsName, 'subindex',
                                superindex=(contentItems, contentItems.__collection__,
                                            self.itsName))
        else:
            # Create a standalone index
            self.makeIndexOn(collection)

    def makeIndexOn(self, collection):
        """ Create the index we describe on this collection """
        raise TypeError(
            "pim.IndexDefinition is an abstract type; use a subtype that " \
            "overrides makeIndexOn"
        )

    def findValues(self, uuid, *pairs):
        return self.findInheritedValues(self.itsView, uuid, *pairs)
    
    @staticmethod
    def findInheritedValues(view, uuid, *pairs):
        """
        Inheritance-aware version of RepositoryView.findValues(), for
        use in IndexDefinitions, mainly.
        
        @param uuid: The UUID to find values for
        @type uuid: C{UUID}
        
        @param pairs: (attribute-name, default-value) pairs to pass to
                       C{RepositoryView.findValues}
        @type pairs: iterable
        
        @return: A C{tuple} of values for the item with C{uuid}, corresponding
                 to the attribute names in  C{pairs}. If the item doesn't have
                 a value for a given attribute, and the item's 'inheritFrom'
                 attribute is non-None, the inheritFrom's value is used instead.
                 (If in turn that item doesn't have the value, the 2nd element
                 of the pair -- the default value -- is what's returned.
        @rtype: C{tuple}
        """
        
        valuesToFind = [('inheritFrom', None)]
        # Use Nil, not None here so that we can distinguish
        # no-value-for-attribute from attribute-value-is-None.
        valuesToFind.extend((attr, Nil) for attr, default in pairs)

        result = view.findValues(uuid, *valuesToFind)
        masterUuid = result[0]
        result = result[1:] # Skip inheritFrom
        nilValues = []
        masterValues = []
        
        # Go through the returned tuple, and see if any results were
        # Nil. If they were, we'll need to call view.findValues on
        # masterUuid (sic).
        for inputTuple, resultValue in zip(pairs, result):
            if resultValue is Nil:
                if masterUuid is None:
                    nilValues.append(inputTuple[1])
                else:
                    masterValues.append(inputTuple)
        if masterValues:
            nilValues = view.findValues(masterUuid, *masterValues)
        
        iterNilValues = iter(nilValues)
        
        return tuple(fetched if fetched is not Nil else iterNilValues.next()
                      for fetched in result)
                      


class NumericIndexDefinition (IndexDefinition):
    """
    A class that allows you to build numeric indexes
    """
    def makeIndexOn(self, collection):
        """ Create the index we describe on this collection """
        collection.addIndex(self.itsName, 'numeric')

class MethodIndexDefinition(IndexDefinition):
    """
    A class that allows you to build indexes based on comparing computed
    attributes (i.e. ones that aren't stored in the repository directly).
    Note that this class reinterprets the 'attributes' attribute of
    IndexDefinition: this is now the attributes to _monitor_ (i.e. the ones
    that trigger recomputing the index).

    @cvar findValuePairs: The pairs you want instances to pass to
                          C{IndexDefinition.findValues()} when the index
                          is asked to compare two UUIDs.
    
    @type findValuePairs: C{tuple}
    """
    findValuePairs = ()

    def makeIndexOn(self, collection):
        """ Create the index we describe on this collection """
        
        monitoredAttributes = (self.attributes or [])
        
        # We need to include inheritFrom in the attributes we monitor,
        # else (especially at Occurrence creation time) items don't get
        # re-indexed properly when they inherit attribute values from
        # their "rich relatives" (ovaltofu's term).
        if not 'inheritFrom' in monitoredAttributes:
            monitoredAttributes = ['inheritFrom'] + monitoredAttributes
            
        collection.addIndex(self.itsName, 'method',
                            method=(self, 'compare'),
                            monitor=monitoredAttributes)

    def compare(self, u1, u2):
        """
        Compare two items, given their UUIDs. This method fetches (using
        findValues() on the item UUIDs) the pairs specified in the
        C{findValuePairs} (class) variable.
        """
        if not self.findValuePairs:
            raise TypeError(
                "pim.MethodIndexDefinition is an abstract type; use a " \
                "subtype that sets findValuePairs"
            )
        v1 = self.findValues(u1, *self.findValuePairs)
        v2 = self.findValues(u1, *self.findValuePairs)
        return cmp(v1, v2)
        
    # @@@ [grant] Unused
    def compareValues(self, v1, v2):
        """
        Override this to implement the comparison between two items. C{v1}
        and C{v2} are C{tuple} objects; the results of calling C{findValues()}
        on C{findValuePairs} for the two items in question.
        """
        
        # Maybe this should default to cmp()?
        raise TypeError(
            "pim.MethodIndexDefinition is an abstract type; use a subtype " \
            "that overrides compare, or compareValues()"
        )

    def __init__(self, *args, **kw):
        # Make the attributes we monitor be the same as the ones we'll
        # fetch in findValues().
        if not kw.get('attributes', ()):
            kw['attributes'] = [tuple[0]
                                 for tuple in type(self).findValuePairs]
        return super(MethodIndexDefinition, self).__init__(*args, **kw)

        

class AttributeIndexDefinition(MethodIndexDefinition):
    """
    A little like AttributeIndexDefinition, except that this looks up
    the attribute values using the findValues() call, thereby taking
    recurring events into account.
    """
    
    def getFindValuePairs(self):
        # Make sure that findValuePairs is initialized correctly. To emulate
        # the behaviour of an attribute index, this has to make sure that
        # attributes with defaultValues are compared/fetched correctly.
        if not self.findValuePairs:
            tuples=[]
            for attr in self.attributes:
                descriptor = getattr(ContentItem, attr, None)
                default = getattr(descriptor, 'defaultValue', None)
                tuples.append((attr, default))
            self.findValuePairs = tuple(tuples)
        return self.findValuePairs

    def compare(self, u1, u2):
        attrs = self.getFindValuePairs() 

        def noneAwareCmp(v1, v2):
            # ... somewhat stolen from Indexes.py in the repository
            # code.
            if v1 is v2:
                return 0
 
            if v1 is None:
                return -1
 
            if v2 is None:
                return 1
 
            return cmp(v1, v2)
        
        for value1, value2 in itertools.izip(
                         self.findValues(u1, *attrs),
                         self.findValues(u2, *attrs)):
            result = noneAwareCmp(value1, value2)
            if result:
                return result
        return 0


class AllIndexDefinitions(schema.Item):
    """
    Singleton item that hosts a reflist of all L{IndexDefinition}s
    in existance: L{IndexDefinition}'s constructor adds each new instance
    to us to assure this.
    """
    indexDefinitions = schema.Sequence(
        IndexDefinition, initialValue=[], inverse=schema.One()
    )



class ContentCollection(ContentItem, Collection):
    """
    The base class for Chandler Collection types.

    This class is abstract. Base concrete subclasses must use the
    C{schema.CollectionClass} metaclass and declare the collection attribute
    and its name as in the examples below::

        __metaclass__ = schema.CollectionClass
        __collection__ = 'ex1'

        ex1 = schema.One(schema.TypeReference('//Schema/Core/AbstractSet'))

    or::

        __metaclass__ = schema.CollectionClass
        __collection__ = 'ex2'

        ex2_collections = schema.Sequence()
        ex2 = schema.Sequence(inverse=ex2_collections, initialValue=[])

    The type of collection value chosen (as declared above) determines which
    methods are delegated from this item to the collection value, typically
    an AbstractSet subclass instance or a RefList instance.
    """

    collectionList = schema.Sequence(
        doc="Views, e.g. the Calendar, that display collections need to know "
            "which collection are combined to make up the calendar. collectionList"
            "is an optional parameter for this purpose."
    )

    # other side of 'collectionList'
    inCollectionListFor = schema.Sequence(inverse=collectionList)

    invitees = schema.Sequence(
        doc="The people who are being invited to share in this item; filled "
            "in when the user types in the DV's 'invite' box, then cleared on "
            "send (entries copied to the share object).\n\n"
            "Issue: Bad that we have just one of these per item collection, "
            "though an item collection could have multiple shares post-0.5",
        initialValue=()
    ) # inverse of osaf.pim.mail.EmailAddress.inviteeOf

    # other side of 'sources'
    sourceFor = schema.Sequence()

    # other side of AppCollection.exclusionsCollection
    exclusionsFor = schema.Sequence()

    # other side of AppCollection.collectionTrash
    trashFor = schema.Sequence()

    schema.addClouds(
        copying = schema.Cloud(invitees),
        sharing = schema.Cloud(none=["displayName"]),
    )

    # this delete hook is necessary because clearing 'sourceFor' depends on
    # watchers still be being there.
    def onItemDelete(self, view, isDeferring):
        #KLUDGE put in as debugging aid after bug 6686 9/14/06
        #remove after 3 months
        if self.itsName == 'allCollection':
            raise ValueError, ('deleting allCollection', self)
        if not isDeferring and hasattr(self, 'sourceFor'):
            self.sourceFor.clear()

    def withoutTrash(self):
        """
        If this collection wraps the trash collection, return an equivalent
        collection that doesn't.
        """

        return self

    
    def _reIndex(self, op, item, attrName, collectionName, indexName):
        collection = getattr(self, collectionName, None)
        if item in collection:
            keys = [item.itsUUID]
            if op in ('set', 'remove') and getattr(item, 'inheritFrom', None) is None:
                mods = getattr(item, 'inheritTo', None)
                
                if mods:
                    keys.extend(mod.itsUUID for mod in mods
                     if mod in collection and
                       not mod.hasLocalAttributeValue(attrName))
            collection.reindexKeys(keys, indexName)

class KindCollection(ContentCollection):
    """
    A ContentCollection of all of the items of a particular kind.

    The C{kind} attribute determines the C{Kind} of the items in the
    C{KindCollection}.

    The C{recursive} attribute determines whether items of subkinds are
    included (C{False}) by default).
    """

    __metaclass__ = schema.CollectionClass
    __collection__ = 'set'

    set = schema.One(schema.TypeReference('//Schema/Core/AbstractSet'))

    kind = schema.One(schema.TypeReference('//Schema/Core/Kind'))
    recursive = schema.One(schema.Boolean, defaultValue=False)

    def __init__(self, *args, **kwds):

        super(KindCollection, self).__init__(*args, **kwds)
        setattr(self, self.__collection__, KindSet(self.kind, self.recursive))


class ListCollection(ContentCollection):
    """
    A ContentCollection that contains only those items that are explicitly
    added to it.

    Items in a ContentCollection are iterated over in order of insertion.

    A ListCollection is backed by a ref collection.
    """

    __metaclass__ = schema.CollectionClass
    __collection__ = 'inclusions'

    # must be named 'inclusions' to match AppCollection
    inclusions = inclusions

    def empty(self):
        for item in self:
            item.delete(True)


class WrapperCollection(ContentCollection):
    """
    A class for collections wrapping other collections
    """

    __metaclass__ = schema.CollectionClass
    __collection__ = 'set'

    set = schema.One(schema.TypeReference('//Schema/Core/AbstractSet'))

    sources = schema.Sequence(inverse=ContentCollection.sourceFor,
                              doc="the collections being wrapped",
                              initialValue=[])
    schema.addClouds(copying=schema.Cloud(byCloud=[sources]))

    def __init__(self, *args, **kwds):

        super(WrapperCollection, self).__init__(*args, **kwds)

        self._sourcesChanged_('add')
        self.watchCollection(self, 'sources', '_sourcesChanged')

    def _sourcesChanged(self, op, item, attribute, sourceId):

        if op in ('add', 'remove'):
            view = self.itsView
            source = view[sourceId]
            name = source.__collection__

            if op == 'add':
                set = self._sourcesChanged_(op)
                sourceChanged = set.sourceChanged
                actualSource = set.findSource(sourceId)
                assert actualSource is not None
                for uuid in source.iterkeys():
                    view._notifyChange(sourceChanged, 'add', 'collection',
                                       source, name, False, uuid, actualSource)

            elif op == 'remove':
                set = getattr(self, self.__collection__)
                sourceChanged = set.sourceChanged
                actualSource = set.findSource(sourceId)
                assert actualSource is not None
                for uuid in source.iterkeys():
                    view._notifyChange(sourceChanged, 'remove', 'collection',
                                       source, name, False, uuid, actualSource)
                set = self._sourcesChanged_(op)

    def addSource(self, source):

        if source not in self.sources:
            self.sources.append(source)

    def removeSource(self, source):

        if source in self.sources:
            self.sources.remove(source)


class SingleSourceWrapperCollection(WrapperCollection):
    """
    A class for collections wrapping another collection
    """

    def _getSource(self):
        sources = self.sources
        if sources:
            return sources.first()
        return None
    def _setSource(self, source):
        sources = self.sources
        if sources:
            if sources.first() is source:
                return
            sources.clear()
        if source is not None:
            sources.append(source)
    def _delSource(self):
        self.sources.clear()
    source = property(_getSource, _setSource, _delSource)

    def __init__(self, *args, **kwds):

        source = kwds.pop('source', None)
        if source is not None:
            kwds['sources'] = [source]

        super(SingleSourceWrapperCollection, self).__init__(*args, **kwds)

    def _sourcesChanged_(self, op):

        source = self.source

        if source is None:
            set = EmptySet()
        else:
            set = Set(source)

        setattr(self, self.__collection__, set)
        return set


class DifferenceCollection(WrapperCollection):
    """
    A ContentCollection containing the set theoretic difference of two
    ContentCollections.

    The C{sources} attribute (a list) contains the ContentCollection
    instances to be differenced.
    """

    def _sourcesChanged_(self, op):

        sources = self.sources
        sourceCount = len(sources)

        if sourceCount == 0:
            set = EmptySet()
        elif sourceCount == 1:
            set = getattr(self, self.__collection__)
            source = sources.first()
            if isinstance(set, Difference):
                if set._left[0] == source.itsUUID:
                    set = Set(source)
                else:
                    set = EmptySet()
            else:
                set = Set(source)
        elif sourceCount == 2:
            a, b = self.sources
            set = Difference(a, b)
        else:
            raise ValueError, 'too many sources'

        setattr(self, self.__collection__, set)
        return set


class UnionCollection(WrapperCollection):
    """
    A ContentCollection containing the set theoretic union of at least two
    ContentCollections.
    """

    def _sourcesChanged_(self, op):

        sources = self.sources
        sourceCount = len(sources)

        # For now, when we join collections with Union, we pull trash
        # out of the equation with withoutTrash()
        if sourceCount == 0:
            set = EmptySet()
        elif sourceCount == 1:
            set = Set(sources.first().withoutTrash())
        elif sourceCount == 2:
            left, right = sources
            set = Union(left.withoutTrash(), right.withoutTrash())
        else:
            set = MultiUnion(*(source.withoutTrash()
                               for source in sources))

        setattr(self, self.__collection__, set)
        return set


class IntersectionCollection(WrapperCollection):
    """
    A ContentCollection containing the set theoretic intersection of at
    least two ContentCollections.
    """

    def _sourcesChanged(self, op, item, attribute, sourceId):

        if op in ('add', 'remove'):
            view = self.itsView
            source = view[sourceId]
            name = self.__collection__
            _collectionChanged = self._collectionChanged

            if op == 'add':
                set = getattr(self, name)
                wasEmpty = isinstance(set, EmptySet)
                if not wasEmpty:
                    sourceSet = getattr(source, source.__collection__)
                    for uuid in set.iterkeys():
                        if uuid not in sourceSet:
                            view._notifyChange(_collectionChanged,
                                               'remove', 'collection',
                                               name, uuid)
                set = self._sourcesChanged_(op)
                if wasEmpty and not isinstance(set, EmptySet):
                    for uuid in set.iterkeys():
                        view._notifyChange(_collectionChanged,
                                           'add', 'collection', name, uuid)

            elif (op == 'remove' and
                  not isinstance(getattr(self, name), EmptySet)):
                set = self._sourcesChanged_(op)
                sourceSet = getattr(source, source.__collection__)
                if isinstance(set, EmptySet):
                    for uuid in sourceSet.iterkeys():
                        view._notifyChange(_collectionChanged,
                                           'remove', 'collection', name, uuid)
                else:
                    for uuid in set.iterkeys():
                        if uuid not in sourceSet:
                            view._notifyChange(_collectionChanged,
                                               'add', 'collection', name, uuid)

    def _sourcesChanged_(self, op):

        sources = self.sources
        sourceCount = len(sources)

        # For now, when we join collections with Intersection, we pull trash
        # out of the equation with withoutTrash()
        if sourceCount < 2:
            set = EmptySet()
        elif sourceCount == 2:
            left, right = sources
            set = Intersection(left.withoutTrash(), right.withoutTrash())
        else:
            set = MultiIntersection(*(source.withoutTrash()
                                      for source in sources))

        setattr(self, self.__collection__, set)
        return set


class FilteredCollection(SingleSourceWrapperCollection):
    """
    A ContentCollection which is the result of applying a boolean predicate
    to every item of another ContentCollection.

    The C{source} attribute contains the ContentCollection instance to be
    filtered.

    The C{filterExpression} attribute is a string containing a Python
    expression. If the expression returns C{True} for an item in the
    C{source} it will be in the FilteredCollection.

    The C{filterAttributes} attribute is a list of attribute names
    (Strings), which are accessed by the C{filterExpression}.
    Failure to provide this list will result in missing notifications.
    """

    filterExpression = schema.One(schema.Text)
    filterMethod = schema.One(schema.Tuple)
    filterAttributes = schema.Sequence(schema.Importable, initialValue=[])

    def _sourcesChanged_(self, op):

        source = self.source
        if source is None:
            s = EmptySet()
        else:
            attrs = tuple(set(self.filterAttributes))
            if hasattr(self, 'filterExpression'):
                s = ExpressionFilteredSet(source, self.filterExpression, attrs)
            else:
                s = MethodFilteredSet(source, self.filterMethod, attrs)

        setattr(self, self.__collection__, s)
        return s


class SetCollection(ContentCollection):
    """
    A collection class to wrap an arbitrary set that doesn't include trash
    """

    __metaclass__ = schema.CollectionClass
    __collection__ = 'set'

    set = schema.One(schema.TypeReference('//Schema/Core/AbstractSet'))

    def withoutTrash(self):
        return self
    

class AppCollection(ContentCollection):
    """
    AppCollections implement inclusions, exclusions, source,
    and trash along with methods for add and remove.
    """

    __metaclass__ = schema.CollectionClass
    __collection__ = 'set'

    set = schema.One(schema.TypeReference('//Schema/Core/AbstractSet'))

    # must be named 'inclusions' to match ListCollection
    inclusions = inclusions

    # the exclusions used when no exclusions collection is given
    collectionExclusions = schema.Sequence(inverse=ContentItem.excludedBy)

    exclusionsCollection = schema.One(inverse=ContentCollection.exclusionsFor,
                                      defaultValue = None)
    trashCollection = schema.One(inverse=ContentCollection.trashFor,
                                 defaultValue = None)

    # an AppCollection may have another collection for exclusions and that
    # other collection may be the global trash collection. If no collection
    # is specified for exclusions, a local ref collection is used instead.

    def _getExclusions(self):
        exclusions = self.exclusionsCollection
        if exclusions is None:
            exclusions = self.collectionExclusions
        return exclusions
    exclusions = property(_getExclusions)

    # an AppCollection may have another collection for trash. If no
    # collection is given for trash, the collection's exclusions is used
    # instead following the logic above.

    def _getTrash(self):
        trash = self.trashCollection
        if trash is None:
            trash = self.exclusions
        return trash
    trash = property(_getTrash)

    # __collection__ denotes a bi-ref set,
    # therefore it must be added to the copying cloud def for it to be copied.

    schema.addClouds(
        copying = schema.Cloud(
            byCloud=[inclusions, collectionExclusions, exclusionsCollection],
            byRef=[trashCollection, __collection__]
        ),
    )

    def add(self, item):
        """
        Add an item to the collection.
        """
        self.inclusions.add(item)

        exclusions = self.exclusions
        if item in exclusions:
            exclusions.remove(item)

        # If a trash is associated with this collection, remove the item
        # from the trash.  This has the additional benefit of having the item
        # reappear in any collection which has the item in its inclusions

        trash = self.trash
        if trash is not None and item in trash:
            trash.remove(item)

    def remove(self, item):
        """
        Remove an item from the collection.
        """

        isDeleting = item.isDeleting()

        # adding to exclusions before determining if the item should be added to
        # the trash was a problem at one point (bug 4551), but since the mine/
        # not-mine mechanism changed, this doesn't seem to be a problem anymore,
        # and removing from a mine collection was actually misbehaving if the
        # test was done first, so now logic for moving to the trash has moved
        # back to after addition to exclusions and removal from inclusions.
        if not isDeleting:
            self.exclusions.add(item)

        if item in self.inclusions:
            self.inclusions.remove(item)

        trash = self.trash
        pim_ns = schema.ns('osaf.pim', self.itsView)

        if not (isDeleting or trash is None):
            if isinstance(trash, ContentCollection):
                for collection in itertools.chain(trash.trashFor,
                                                  [pim_ns.allCollection]):
                    # allCollection isn't in trash.trashFor, but needs to be
                    # considered
                    if collection is not self and item in collection:
                        # it exists somewhere else, definitely don't add
                        # to trash
                        break
                else:
                    # we couldn't find it anywhere else, so it goes in the trash
                    trash.add(item)

    def __init__(self, itsName=None, itsParent=None,
                 itsKind=None, itsView=None,
                 source=None, exclusions=None, trash=Default,
                 *args, **kwds):
        super(AppCollection, self).__init__(itsName=itsName,
                                            itsParent=itsParent,
                                            itsKind=itsKind,
                                            itsView=itsView,
                                            *args, **kwds)
        self._setup(source, exclusions, trash)

    def _setup(self, source=None, exclusions=None, trash=Default):
        """
        Setup all the extra parts of an AppCollection. In general
        nobody should call this but __init__, but unfortunately
        sharing creates AppCollections without calling __init__
        so it should be the only caller of _setup.

        Sets the source, exclusions and trash collections.

        In general trash should only be the well known Trash
        collection or None. None indicates that this collection does
        not participate in Trash-based activities.

        The special value of Default for trash is only a sentinel to
        let us know that nothing has been passed in and that the
        default trash should be looked up in osaf.pim. During parcel
        loading, this allows us to pass the trash into the constructor
        and avoid trying to look it up in osaf.pim while osaf.pim is
        being loaded.
        """

        if trash is Default:
            # better hope osaf.pim has been loaded!
            trash = schema.ns('osaf.pim', self.itsView).trashCollection

        innerSource = (self, 'inclusions')
        if source is not None:
            innerSource = Union(source, innerSource)

        # Typically we will create a collectionExclusions ref collection;
        # however, a collection like 'All' will instead want to use the
        # Trash collection for exclusions

        if exclusions is None:
            self.collectionExclusions = []
            set = Difference(innerSource, (self, 'collectionExclusions'))
        else:
            self.exclusionsCollection = exclusions
            set = Difference(innerSource, exclusions)

        # You can designate a certain ListCollection to be used for this
        # collection's trash; in this case, an additional DifferenceCollection
        # will be created to remove any trash items from this collection. Any
        # collections which share a trash get the following benefits:
        # - Adding an item to the trash will make the item disappear from
        #   collections sharing that trash collection
        # - When an item is removed from a collection, it will automatically
        #   be moved to the trash if it doesn't appear in any collection which
        #   shares that trash

        if trash is not None:
            set = Difference(set, trash)
            self.trashCollection = trash

        setattr(self, self.__collection__, set)

    def withoutTrash(self):
        """
        Pull out the non-trash part of AppCollection.
        """

        # Smart collections are 'special' - they almost always include
        # the trash as a part of their structure on the _right side of
        # their Difference set. This means that when they are hooked
        # into a larger collection tree, they need to only give out
        # the _left side, which has no trash.

        if self.trash is schema.ns('osaf.pim', self.itsView).trashCollection:
            return self.set._left.copy(self.itsUUID)

        return self


class SmartCollection(AppCollection):
    """
    A SmartCollection is just an AppCollection that is user-facing.
    """
    __metaclass__ = schema.CollectionClass
    __collection__ = 'set'

    # it's an AbstractSet because cardinality is 'set' (schema.Many)
    # it's an AbstractSet of bi-directional references
    set = schema.Many(inverse=ContentItem.appearsIn)

    # this delete hook is necessary because clearing the set of bi-refs
    # may depend on collections that are children of this one
    def onItemDelete(self, view, isDeferring):
        super(SmartCollection, self).onItemDelete(view, isDeferring)
        if not isDeferring:
            name = self.__collection__
            delattr(self, name)
            for watch in getattr(self, 'watches', ()):
                if watch.attribute == name:
                    watch.delete()


class IndexedSelectionCollection(SingleSourceWrapperCollection):
    """
    A collection that adds an index, e.g. for sorting items, a
    selection and visibility attribute to another source collection.
    """

    indexName = schema.One(schema.Importable, initialValue="__adhoc__")

    def _sourcesChanged_(self, op):

        source = self.source

        if source is None:
            set = EmptySet()
            if op == 'remove':
                self.delete()
                return set
        elif isinstance(source, WrapperCollection):
            # bug 5899 - alpha2 workaround: When SmartCollections are
            # wrapped with IntersectionCollection/UnionCollection,
            # they drop the trash. So we artificially insert it back
            trash = schema.ns('osaf.pim', self.itsView).trashCollection
            for item, attribute in source.iterSources(True):
                if item is trash and attribute == trash.__collection__:
                    set = Set(source)
                    break
            else:
                set = Difference(source, trash)
        else:
            set = Set(source)

        setattr(self, self.__collection__, set)
        return set

    def getCollectionIndex(self, indexName=None):
        """
        Get the index. If it doesn't exist (and C{indexName} isn't "__adhoc__"),
        look up its IndexDefinition and create it. (If it is "__adhoc__",
        create a numeric index under that name.)

        Also, create a RangeSet for storing the selection on the index.
        """
        if indexName is None:
            indexName = self.indexName

        if not self.hasIndex(indexName):
            if indexName == "__adhoc__":
                self.addIndex(indexName, 'numeric')
            else:
                IndexDefinition.makeIndexByName(self, indexName)
            self.setRanges(indexName, [])
        return self.getIndex(indexName)

    def setCollectionIndex(self, newIndexName, toggleDescending=False):
        """
        Switches to a different index, bringing over the selection to
        the new index.

        If toggleDescending is C{True}, then when the indexName is set
        to the current indexName, the sort will toggle its Descending
        status, and reset the selection to match.
        """

        # assuming that we'll have to redo selection when sort is reversed?
        currentIndexName = self.indexName
        newIndex = self.getCollectionIndex(newIndexName)
        if currentIndexName != newIndexName:
            # new index - bring over the items one by one
            self.setRanges(newIndexName, [])

            for item in self.iterSelection():
                newItemIndex = self.positionInIndex(newIndexName, item)
                self.addRange(newIndexName, (newItemIndex, newItemIndex))

            self.indexName = newIndexName
        elif toggleDescending:
            itemMax = len(self) - 1
            newRanges = []
            # build the ranges in reverse, so the resulting ranges are
            # in order
            for start,end in reversed(self.getSelectionRanges()):
                (newStart, newEnd) = (itemMax - end, itemMax - start)
                newRanges.append((newStart, newEnd))

            self.setDescending (currentIndexName, not self.isDescending(currentIndexName))
            self.setSelectionRanges(newRanges)

    def __len__(self):

        return len(self.getCollectionIndex())

    def moveItemToLocation (self, item, location):
        """
        Moves an item to a new C{location} in an __adhoc__ index.
        """
        if location == 0:
            # Get the index. It's necessary to get the length, and if
            # it doesn't exist getCollectionIndex will create it.
            self.getCollectionIndex()
            before = None
        else:
            before = self [location - 1]
        self.placeInIndex(item, before, self.indexName)

    #
    # General selection methods
    #

    def isSelectionEmpty(self):
        return len(self.getSelectionRanges()) == 0

    def clearSelection(self):
        return self.setSelectionRanges([])

    #
    # Range-based selection methods
    #

    def getSelectionRanges(self):
        """
        Return the ranges associated with the current index as an
        array of tuples, where each tuple represents a start and
        end of the range.
        """
        return self.getCollectionIndex().getRanges()

    def setSelectionRanges(self, ranges):
        """
        Sets the ranges associated with the current index with
        C{ranges} which should be an array of tuples, where each
        tuple represents a start and end of the range.  The C{ranges}
        must be sorted ascending, non-overlapping and postive.
        """
        self.setRanges(self.indexName, ranges)

    def isSelected(self, range):
        """
        Returns C{True} if the C{range} is completely inside the selected
        ranges of the index.  C{range} may be a tuple: (start, end) or
        an integer index, where negative indexing works like Python
        indexing.
        """
        return self.getCollectionIndex().isInRanges(range)

    def addSelectionRange(self, range):
        """
        Selects a C{range} of indexes. C{range} may be a tuple:
        (start, end) or an integer index, where negative indexing
        works like Python indexing.
        """
        self.addRange(self.indexName, range)

    def removeSelectionRange(self, range):
        """
        Unselects a C{range} of indexes. C{range} may be a tuple:
        (start, end) or an integer index, where negative indexing
        works like Python indexing.
        """
        self.removeRange(self.indexName, range)
    #
    # Item-based selection methods
    #

    def setSelectionToItem(self, item):
        """
        Sets the entire selection to include only the C{item}.
        """
        index = self.index (item)
        self.setRanges(self.indexName, [(index, index)])

    def getFirstSelectedItem(self):
        """
        Returns the first selected item in the index or C{None} if
        there is no selection.
        """
        index = self.getCollectionIndex()._ranges.firstSelectedIndex()
        if index == None:
            return None
        return self[index]

    def isItemSelected(self, item):
        """
        Returns C{True}/C{False} based on if the item is actually
        selected or not
        """
        return item is not None and self.isSelected(self.index(item))

    def iterSelection(self):
        """
        Generator to get the selection.
        """
        ranges = self.getSelectionRanges()
        if ranges is not None:
            for start,end in ranges:
                for idx in range(start,end+1):
                    yield self[idx]

    def selectItem(self, item):
        """
        Selects an C{item} in the index.
        """
        self.addSelectionRange (self.index (item))

    def unselectItem(self, item):
        """
        Unselects an C{item} in the index.
        """
        self.removeSelectionRange (self.index (item))

    #
    # index-based methods
    #

    def __getitem__(self, index):
        """
        Support indexing using [].
        """
        # Get the index. It's necessary to get the length, and if it doesn't exist
        # getCollectionIndex will create it.
        self.getCollectionIndex()
        return self.getByIndex(self.indexName, index)

    def index(self, item):
        """
        Return the position of item in the index.
        """

        # Get the index. It's necessary to get the length, and if it doesn't
        # exist getCollectionIndex will create it.

        self.getCollectionIndex()
        return self.positionInIndex(self.indexName, item)

    def add(self, item):
        self.source.add(item)

    def clear(self):
        self.source.clear()

    def first(self):
        return self.source.first()

    def remove(self, item):
        self.source.remove(item)

    def empty(self):
        self.source.empty()
