"""
Repository of the Cobbler object model

Copyright 2006-2009, Red Hat, Inc and Others
Michael DeHaan <michael.dehaan AT gmail>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301  USA
"""

import time
import weakref
import uuid
from typing import Union, Dict, Any

from cobbler.api import CobblerAPI
from cobbler.cexceptions import CX
from cobbler import settings
from cobbler import serializer
from cobbler.cobbler_collections.collection import Collection
from cobbler.cobbler_collections.distros import Distros
from cobbler.cobbler_collections.files import Files
from cobbler.cobbler_collections.images import Images
from cobbler.cobbler_collections.mgmtclasses import Mgmtclasses
from cobbler.cobbler_collections.packages import Packages
from cobbler.cobbler_collections.profiles import Profiles
from cobbler.cobbler_collections.repos import Repos
from cobbler.cobbler_collections.systems import Systems
from cobbler.items.item import Item
from cobbler.settings import Settings


class CollectionManager:
    """
    Manages a definitive copy of all data cobbler_collections with weakrefs pointing back into the class so they can
    understand each other's contents.
    """

    has_loaded = False
    __shared_state: Dict[str, Any] = {}

    def __init__(self, api):
        """
        Constructor which loads all content if this action was not performed before.
        """
        self.__dict__ = CollectionManager.__shared_state
        if not CollectionManager.has_loaded:
            self.__load(api)

    def __load(self, api):
        """
        Load all collections from the disk into Cobbler.

        :param api: The api to resolve information with.
        """
        CollectionManager.has_loaded = True

        self.init_time = time.time()
        self.current_id = 0
        self.api = api
        self._distros = Distros(weakref.proxy(self))
        self._repos = Repos(weakref.proxy(self))
        self._profiles = Profiles(weakref.proxy(self))
        self._systems = Systems(weakref.proxy(self))
        self._images = Images(weakref.proxy(self))
        self._mgmtclasses = Mgmtclasses(weakref.proxy(self))
        self._packages = Packages(weakref.proxy(self))
        self._files = Files(weakref.proxy(self))
        # Not a true collection
        self._settings = settings.Settings()

    def generate_uid(self):
        """
        Cobbler itself does not use this GUID's though they are provided to allow for easier API linkage with other
        applications. Cobbler uses unique names in each collection as the object id aka primary key.

        :return: A version 4 UUID according to the python implementation of RFC 4122.
        """
        return uuid.uuid4().hex

    def distros(self) -> Distros:
        """
        Return the definitive copy of the Distros collection
        """
        return self._distros

    def profiles(self) -> Profiles:
        """
        Return the definitive copy of the Profiles collection
        """
        return self._profiles

    def systems(self) -> Systems:
        """
        Return the definitive copy of the Systems collection
        """
        return self._systems

    def settings(self) -> Settings:
        """
        Return the definitive copy of the application settings
        """
        return self._settings

    def repos(self) -> Repos:
        """
        Return the definitive copy of the Repos collection
        """
        return self._repos

    def images(self) -> Images:
        """
        Return the definitive copy of the Images collection
        """
        return self._images

    def mgmtclasses(self) -> Mgmtclasses:
        """
        Return the definitive copy of the Mgmtclasses collection
        """
        return self._mgmtclasses

    def packages(self) -> Packages:
        """
        Return the definitive copy of the Packages collection
        """
        return self._packages

    def files(self) -> Files:
        """
        Return the definitive copy of the Files collection
        """
        return self._files

    def serialize(self):
        """
        Save all cobbler_collections to disk
        """

        serializer.serialize(self._distros)
        serializer.serialize(self._repos)
        serializer.serialize(self._profiles)
        serializer.serialize(self._images)
        serializer.serialize(self._systems)
        serializer.serialize(self._mgmtclasses)
        serializer.serialize(self._packages)
        serializer.serialize(self._files)

    # pylint: disable=R0201
    def serialize_item(self, collection: Collection, item: Item):
        """
        Save a collection item to disk

        :param collection: Collection
        :param item: collection item
        """

        return serializer.serialize_item(collection, item)

    # pylint: disable=R0201
    def serialize_delete(self, collection: Collection, item: Item):
        """
        Delete a collection item from disk

        :param collection: collection
        :param item: collection item
        """

        return serializer.serialize_delete(collection, item)

    def deserialize(self):
        """
        Load all cobbler_collections from disk

        :raises CX: if there is an error in deserialization
        """

        for collection in (
            self._settings,
            self._distros,
            self._repos,
            self._profiles,
            self._images,
            self._systems,
            self._mgmtclasses,
            self._packages,
            self._files,
        ):
            try:
                serializer.deserialize(collection)
            except Exception as e:
                raise CX("serializer: error loading collection %s: %s. Check /etc/cobbler/modules.conf"
                         % (collection.collection_type(), e)) from e

    def get_items(self, collection_type: str) -> Union[Distros, Profiles, Systems, Repos, Images, Mgmtclasses, Packages,
                                                       Files, Settings]:
        """
        Get a full collection of a single type.

        Valid Values vor ``collection_type`` are: "distro", "profile", "repo", "image", "mgmtclass", "package", "file"
        and "settings".

        :param collection_type: The type of collection to return.
        :return: The collection if ``collection_type`` is valid.
        :raises CX: If the ``collection_type`` is invalid.
        """
        result: Union[Distros, Profiles, Systems, Repos, Images, Mgmtclasses, Packages, Files, Settings]
        if collection_type == "distro":
            result = self._distros
        elif collection_type == "profile":
            result = self._profiles
        elif collection_type == "system":
            result = self._systems
        elif collection_type == "repo":
            result = self._repos
        elif collection_type == "image":
            result = self._images
        elif collection_type == "mgmtclass":
            result = self._mgmtclasses
        elif collection_type == "package":
            result = self._packages
        elif collection_type == "file":
            result = self._files
        elif collection_type == "settings":
            result = self._settings
        else:
            raise CX("internal error, collection name %s not supported" % collection_type)
        return result
