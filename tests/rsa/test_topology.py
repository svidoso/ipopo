#!/usr/bin/env python
# -- Content-Encoding: UTF-8 --
"""
Tests the RSA basic topology manager

:author: Thomas Calmant
"""

# Standard library
try:
    import unittest2 as unittest
except ImportError:
    import unittest

try:
    from typing import List
except ImportError:
    pass

# Pelix
from pelix.ipopo.constants import use_ipopo
import pelix.constants
import pelix.framework

# Remote Services
import pelix.rsa.remoteserviceadmin as rsa

# ------------------------------------------------------------------------------

__version__ = "1.0.0"

# ------------------------------------------------------------------------------


class TopologyManagerTest(unittest.TestCase):
    """
    Tests RSA basic topology manager
    """

    def setUp(self):
        """
        Prepares a framework and a registers a service to export
        """
        # Create the framework
        self.framework = pelix.framework.create_framework(
            ["pelix.ipopo.core", "pelix.http.basic",
             "pelix.rsa.remoteserviceadmin",
             "pelix.rsa.providers.distribution.xmlrpc"],
            {"ecf.xmlrpc.server.hostname": "localhost"})
        self.framework.start()

        # Get the RSA service
        context = self.framework.get_bundle_context()
        self.rsa = context.get_service(
            context.get_service_reference(
                rsa.SERVICE_REMOTE_SERVICE_ADMIN))  # type: rsa.RemoteServiceAdminImpl

        # Start an HTTP server, required by XML-RPC
        with use_ipopo(context) as ipopo:
            ipopo.instantiate(
                'pelix.http.service.basic.factory',
                'http-server',
                {'pelix.http.address': 'localhost',
                 'pelix.http.port': 0})

    def tearDown(self):
        """
        Stops the framework
        """
        self.framework.delete(True)

    def test_auto_export(self):
        """
        Tests an export of a service (with XML-RPC)
        """
        # Install the topology manager
        context = self.framework.get_bundle_context()
        context.install_bundle("pelix.rsa.topologymanagers.basic").start()

        # Register a service to be exported
        spec = "test.svc"
        svc = object()
        svc_reg = context.register_service(
            spec, svc,
            {
                rsa.SERVICE_EXPORTED_INTERFACES: '*',
                rsa.SERVICE_EXPORTED_CONFIGS: "ecf.xmlrpc.server"
            }
        )
        svc_ref = svc_reg.get_reference()

        # Check if it has been exported
        for export_ref in self.rsa.get_exported_services():
            if export_ref.get_reference() is svc_ref:
                break
        else:
            self.fail("Service not automatically exported")

        # Update service
        key = "foo"
        val = "bar"
        svc_reg.set_properties({key: val})
        for export_ref in self.rsa.get_exported_services():
            if export_ref.get_reference() is svc_ref:
                svc_val = export_ref.get_description().get_properties()[key]
                self.assertEqual(val, svc_val)
                break
        else:
            self.fail("No update of service properties")

        # Unregister the service
        svc_reg.unregister()

        # Check if it is still exported
        for export_ref in self.rsa.get_exported_services():
            if export_ref.get_reference() is svc_ref:
                self.fail("Service not automatically removed")
