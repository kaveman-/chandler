"""
@copyright: Copyright (c) 2004 Open Source Applications Foundation
@license: U{http://osafoundation.org/Chandler_0.1_license_terms.htm}
"""
__parcel__ = "//Schema/Core"

import sys, os, logging
from datetime import datetime

import schema
import application.Globals as Globals

logger = logging.getLogger(__name__)


#@@@Temporary testing tool written by Morgen -- DJA
timing = False
if timing: import util.timing

class Manager(schema.Item):
    """
    To use the parcel manager, retrieve an instance of it by using the class
    method get()::

        import application
        mgr = application.Parcel.Manager.get(view, path=parcelSearchPath)
        mgr.loadParcels()

    if "path" is not passed in, it will use
    os.path.join(Globals.chandlerDirectory, "parcels").
    """

    path = schema.Sequence(schema.String, initialValue = [])

    @classmethod
    def get(cls, view, path=None):
        """
        Class method for getting an instance of the parcel manager.

        If there is a manager item already already in this repository, that
        will be returned.  Otherwise one will be created.

        @param view: The repository view object to load items into.
        @type view: L{repository.persistence.RepositoryView}
        @param path: The search path for finding parcels.  This is a list
        of absolute directory paths; when loading parcels, each directory
        in the search path will be used as a starting point for recursively
        finding parcel.xml files.
        @type path: list
        @return: parcel manager object
        """

        parcelRoot = view.findPath("//parcels")
        if parcelRoot is None:
            parcelRoot = Parcel("parcels",view)
            
        manager = view.findPath("//parcels/manager")
        if manager is None:
            manager = Manager("manager", parcelRoot)           

        if path:
            manager.path = path
        elif not manager.path:
            manager.path = [os.path.join(Globals.chandlerDirectory, "parcels")]

        return manager


    def __syncParcel(self, pkg):
        """Synchronize the specified parcel's Python schema with self.repo

        This will import the corresponding Python module and synchronize its
        schema with the repository.  If the imported module has a parent module
        that has not yet been synchronized, this method will load the parent
        parcel, thereby synchronizing the parent module first.
        """
        if pkg in self._imported:
            return  # skip already-processed parcels
        else:
            self._imported.add(pkg)

        if '.' in pkg:
            # load parent first - even though schema API does this too,
            # the parcel loader will get confused and not load the
            # parent parcel correctly, unless we process it here.  :(
            parent_pkg = pkg.rsplit('.',1)[0]
            if parent_pkg not in self._imported:
                self.__syncParcel(parent_pkg)

        # Last, but not least, actually synchronize the package
        schema.synchronize(self.itsView, pkg)


    def findPlugins(self):
        """Yield top-level parcels"""
        from glob import glob
        for directory in self.path:
            for initfile in glob(os.path.join(directory,'*','__init__.py')):
                yield os.path.basename(os.path.dirname(initfile))


    def loadParcels(self, namespaces=None):
        """
        Load parcel items into the repository.

        The namespaces passed in via the namespaces parameter (a list) are then
        loaded into the repository.  If that parameter is None, then all parcels
        are loaded.

        @param namespaces: The list of namespaces to load
        @type namespace: list of strings
        """
        #@@@Temporary testing tool written by Morgen -- DJA
        if timing: util.timing.begin("Load parcels")

        self._imported = set()    # imported namespaces

        if not namespaces:
            namespaces = sorted(self.findPlugins())
            appParcel = getattr(
                getattr(Globals,'options',None), "appParcel", "osaf.app"
            )                
            # always load the app parcel first
            namespaces.insert(0, appParcel)

        logger.info("Loading parcels...")
        for namespace in namespaces:
            self.__syncParcel(namespace)
        logger.info("...done")               

        #@@@Temporary testing tool written by Morgen -- DJA
        if timing: util.timing.end("Load parcels")

        
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

class Parcel(schema.Item):
    """
    The parcel item class.
    """
    author = schema.One(schema.String)
    publisher = schema.One(schema.String)
    status = schema.One(schema.String)
    summary = schema.One(schema.String)
    icon = schema.One(schema.String)
    version = schema.One(schema.String)
    createdOn = schema.One(schema.DateTime)
    modifiedOn = schema.One(schema.DateTime)
    namespace = schema.One(schema.String, defaultValue = '')
    namespaceMap = schema.Mapping(schema.String, initialValue = {})
    file = schema.One(schema.String, initialValue = '')
    originalValues = schema.Mapping(schema.Dictionary, initialValue = {})

    def __init__(self, *args, **kw):
        super(Parcel, self).__init__(*args, **kw)
        self.createdOn = datetime.now()
        self.modifiedOn = self.createdOn


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

class Reference(schema.Item):
    item = schema.One(
        schema.Item,
        initialValue = None,
        otherName = 'references'
    )

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

