#!/usr/bin/env python
# -- Content-Encoding: UTF-8 --
"""
Loads and handles the Pelix initialization file

A configuration file is used to setup a Pelix framework. This module should
be used by shells to load a default configuration.

:author: Thomas Calmant
:copyright: Copyright 2016, Thomas Calmant
:license: Apache License 2.0
:version: 0.6.4

..

    Copyright 2016 Thomas Calmant

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.
"""

# Standard library
import json
import os
import sys

# Pelix
from pelix.ipopo.constants import use_ipopo

# ------------------------------------------------------------------------------

# Module version
__version_info__ = (0, 6, 4)
__version__ = ".".join(str(x) for x in __version_info__)

# Documentation strings format
__docformat__ = "restructuredtext en"


# -----------------------------------------------------------------------------


def remove_duplicates(items):
    """
    Returns a list without duplicates

    :param items: A list of items
    :return: The list without duplicates
    """
    if not items:
        return items
    else:
        new_list = []
        for item in items:
            if item not in new_list:
                new_list.append(item)
        return new_list


class _Configuration(object):
    """
    Represents a configuration loaded from an initialization file
    """

    def __init__(self):
        """
        Sets up members
        """
        self._properties = {}
        self._environment = {}
        self._paths = []

        self._bundles = []
        self._components = {}

    @property
    def properties(self):
        """
        Returns the configured framework properties

        :return: A dictionary of framework properties
        """
        return self._properties

    @property
    def paths(self):
        """
        Returns the paths to add to sys.path

        :return: A list of paths
        """
        return self._paths

    @property
    def bundles(self):
        """
        Returns the list of bundles to install and start

        :return: A list of names of bundles
        """
        return self._bundles

    @property
    def components(self):
        """
        Returns the definitions of components as a dictionary of tuples.

        Keys are components names, whereas values are (factory, properties)
        tuples

        :return: A name->(factory, properties) dictionary
        """
        return self._components

    def add_properties(self, properties):
        """
        Updates the framework properties dictionary

        :param properties: New framework properties to add
        """
        if isinstance(properties, dict):
            self._properties.update(properties)

    def set_properties(self, properties):
        """
        Sets the framework properties dictionary

        :param properties: Framework properties to set
        """
        self._properties = {}
        self.add_properties(properties)

    def add_environment(self, environ):
        """
        Updates the environment dictionary with the given one.

        Existing entries are overridden by the given ones

        :param environ: New environment variables
        """
        if isinstance(environ, dict):
            self._environment.update(environ)

    def set_environment(self, environ):
        """
        Updates the environment dictionary with the given one.
        Cancels the variables previously set.

        :param environ: New environment variables
        """
        self._environment = {}
        self.add_environment(environ)

    def add_paths(self, paths):
        """
        Adds entries to the Python path.

        The given paths are normalized before being added to the left of the
        list

        :param paths: New paths to add
        """
        if paths:
            # Use new paths in priority
            self._paths = list(paths) + self._paths

    def set_paths(self, paths):
        """
        Adds entries to the Python path.

        The given paths are normalized before being added to the left of the
        Python path.
        Previous paths from configuration files are cleared.

        :param paths: New paths to add
        """
        del self._paths[:]
        self.add_paths(paths)

    def add_bundles(self, bundles):
        """
        Adds a list of bundles to install.

        Contrary to paths and environment variables, the bundles are kept in
        the system-wide to user-specific order.

        :param bundles: A list of bundles to install
        """
        if bundles:
            self._bundles.extend(bundles)

    def set_bundles(self, bundles):
        """
        Adds a list of bundles to install.
        Previous names from configuration files are cleared.

        Contrary to paths and environment variables, the bundles are kept in
        the system-wide to user-specific order.

        :param bundles: A list of bundles to install
        """
        del self._bundles[:]
        self.add_bundles(bundles)

    def add_components(self, components):
        """
        Adds a list of components to instantiate

        :param components: The description of components
        :raise KeyError: Missing component configuration
        """
        if components:
            for component in components:
                self._components[component['name']] = \
                    (component['factory'], component.get('properties', {}))

    def set_components(self, components):
        """
        Adds a list of components to instantiate.
        Removes the previously configured components descriptions.

        :param components: The description of components
        :raise KeyError: Missing component configuration
        """
        self._components.clear()
        self.add_components(components)

    def normalize(self):
        """
        Normalizes environment variables, paths and filters the lists of
        bundles to install and start.

        After this call, the environment variables of this process will have
        been updated.
        """
        # Add environment variables
        os.environ.update(self._environment)

        # Normalize paths and avoid duplicates
        self._paths = remove_duplicates(
            os.path.realpath(os.path.expanduser(os.path.expandvars(path)))
            for path in self._paths if os.path.exists(path))

        # Normalize the lists of bundles
        self._bundles = remove_duplicates(self._bundles)


class InitFileHandler(object):
    """
    Parses and handles the instructions of the initialization file
    """
    DEFAULT_PATH = ("/etc/default", "/etc", "/usr/local/etc",
                    "~/.local/pelix", "~/.config", "~", ".")
    """
    Default path where to find the configuration file.
    Order is from system wide to user specific configuration.
    """

    def __init__(self):
        """
        Sets up members
        """
        # The internal state
        self.__state = _Configuration()

    @property
    def bundles(self):
        """
        Returns the configured bundles

        :return: The list of bundles to install and start
        """
        return self.__state.bundles

    @property
    def properties(self):
        """
        Returns the configured framework properties

        :return: The initial framework properties
        """
        return self.__state.properties

    def clear(self):
        """
        Clears the current internal state (cleans up loaded content)
        """
        # Reset the internal state
        self.__state = _Configuration()

    def find_default(self, filename):
        """
        A generate which looks in common folders for the default configuration
        file. The paths goes from system defaults to user specific files.

        :param filename: The name of the file to find
        :return: The complete path to the found files
        """
        for path in self.DEFAULT_PATH:
            # Normalize path
            path = os.path.expanduser(os.path.expandvars(path))
            fullname = os.path.realpath(os.path.join(path, filename))

            if os.path.exists(fullname) and os.path.isfile(fullname):
                yield fullname

    def load(self, filename=None):
        """
        Loads the given file and adds its content to the current state.
        This method can be called multiple times to merge different files.

        If no filename is given, this method loads all default files found.
        It returns False if no default configuration file has been found

        :param filename: The file to load
        :return: True if the file has been correctly parsed, False if no file
                 was given and no default file exist
        :raise IOError: Error loading file
        """
        if not filename:
            for name in self.find_default(".pelix.conf"):
                self.load(name)
        else:
            with open(filename, "r") as fp:
                self.__parse(json.load(fp))

    def __parse(self, configuration):
        """
        Parses the given configuration dictionary

        :param configuration: A configuration as a dictionary (JSON object)
        """
        for entry in ('properties', 'environment', 'paths',
                      'bundles', 'components'):
            # Check if current values must be reset
            reset_key = 'reset_{0}'.format(entry)

            # Compute the name of the method
            call_name = "add" if not configuration.get(reset_key) else "set"
            method = getattr(self.__state, "{0}_{1}".format(call_name, entry))

            # Update configuration
            method(configuration.get(entry))

    def normalize(self):
        """
        Normalizes environment variables and the Python path.

        This method updates the environment variables (``os.environ``) and
        the Python path (``sys.path``).
        """
        # Normalize configuration
        self.__state.normalize()

        # Update sys.path, avoiding duplicates
        whole_path = list(self.__state.paths)
        whole_path.extend(sys.path)

        # Ensure the working directory as first search path
        sys.path = ['.']
        for path in whole_path:
            if path not in sys.path:
                sys.path.append(path)

    def instantiate_components(self, context):
        """
        Instantiate the defined components

        :param context: A :class:`BundleContext` object
        :raise BundleException: Error starting a component
        """
        with use_ipopo(context) as ipopo:
            for name, (factory, properties) in self.__state.components.items():
                ipopo.instantiate(factory, name, properties)