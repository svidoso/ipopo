#!/usr/bin/env python
# -- Content-Encoding: UTF-8 --
"""
Pelix remote service admin package

:author: Scott Lewis
:copyright: Copyright 2016, Composent, Inc.
:license: Apache License 2.0
:version: 0.1.0

..

    Copyright 2016 Composent, Inc., Thomas Calmont and others.

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
import logging

# Module version
__version_info__ = (0, 1, 0)
__version__ = ".".join(str(x) for x in __version_info__)

# Documentation strings format
__docformat__ = "restructuredtext en"

# ------------------------------------------------------------------------------
_logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------

# Remote Services constants
import pelix.constants
# iPOPO decorators
from pelix.ipopo.decorators import ComponentFactory, Provides, \
    Instantiate, Validate, Invalidate, Requires, BindField, UnbindField

import pelix.rsa as rsa
from pelix.rsa import SelectExporterError, SelectImporterError
import threading
from pelix.rsa.endpointdescription import EndpointDescription
from argparse import ArgumentError
from pelix.internals.registry import ServiceReference
from pelix import constants
from threading import RLock

class _ImportEndpoint(object):
    
    def __init__(self, rsa, importer, ed, svc_reg):
        self.__rsa = rsa
        self.__importer = importer
        self.__ed = ed
        self.__svc_reg = svc_reg
        self.__lock = threading.RLock()
        self.__active_registrations = []
    
    def _add_import_registration(self, import_reg):
        with self.__lock:
            self.__active_registrations.append(import_reg)

    def _rsa(self):
        return self.__rsa
        
    def _matched(self,ed):
        with self.__lock:
            if len(self.__active_registrations) is 0:
                return False
            return self.__ed.is_same_service(ed)
    def reference(self):
        with self.__lock:
            return None if self.__importer is None else self.__svc_reg.get_reference()
        
    def description(self):
        with self.__lock:
            return self.__ed
        
    def importerid(self):
        with self.__lock:
            return None if self.__importer is None else self.__importer.get_id()

    def update(self, ed):
        with self.__lock:
            if self.__svc_reg is None:
                return None
            new_props = self.__rsa._create_proxy_properties(ed,self.__proxy)
            ed.update(new_props.get_properties())
            self.__ed = ed
            self.__svc_reg.set_properties(self.__ed.get_properties())

    def close(self, import_reg):
        with self.__lock:
            try:
                self.__active_registrations.remove(import_reg)
            except ValueError:
                return False
            if len(self.__active_registrations) is 0:
                try:
                    removed = self.__importer.unimport_service(self.__ed)
                except Exception as e:
                    _logger.error(e)
                    return False
                if removed:
                    self.__rsa._remove_imported_service(import_reg)
                    self.__svc_reg = None
                    self.__importer = None
                    self.__ed = None
                    self.__rsa = None
                    return True
        return False        

class ImportReference(object):
    
    @classmethod
    def fromendpoint(cls,endpoint):
        return cls(endpoint=endpoint)
    
    @classmethod
    def fromexception(cls,e,errored):
        return cls(endpoint=None,exception=e,errored=errored)

    def __init__(self,endpoint=None,exception=None,errored=None):
        self.__lock = threading.RLock()
        if endpoint is None:
            if exception is None or errored is None:
                raise ArgumentError('Must supply either endpoint or throwable/errorEndpointDescription')
            self.__exception = exception
            self.__errored = errored
            self.__endpoint = None
        else:
            self.__endpoint = endpoint
            self.__exception = None
            self.__errored = None
        
    def _importendpoint(self):
        with self.__lock:
            return self.__endpoint
        
    def _matched(self,ed):
        with self.__lock:
            return None if self.__endpoint is None else self.__endpoint._matched(ed)

    def importerid(self):
        with self.__lock:
            return None if self.__endpoint is None else self.__endpoint.importerid()
    
    def reference(self):
        with self.__lock:
            return None if self.__endpoint is None else self.__endpoint.reference()
    
    def description(self):
        with self.__lock:
            return self.errored if self.__endpoint is None else self.__endpoint.description()
    
    def exception(self):
        return self.__exception
    
    def update(self,ed):
        with self.__lock:
            return None if self.__endpoint is None else self.__endpoint.update(ed)
        
    def close(self,import_reg):
        with self.__lock:
            if self.__endpoint is None:
                return False
            else:
                result = self.__endpoint.close(import_reg)
                self.__endpoint = None
                return result
        
class ImportRegistration(object):

    @classmethod
    def fromendpoint(cls,rsa,importer,ed,svc_reg):
        return cls(endpoint=_ImportEndpoint(rsa,importer,ed,svc_reg))
    
    @classmethod
    def fromexception(cls,exception,errored):
        return cls(endpoint=None,exception=exception,errored=errored)
    
    @classmethod
    def fromreg(cls,reg):
        return cls(endpoint=reg._importendpoint())
    
    def __init__(self,endpoint=None,exception=None,errored=None):
        if endpoint is None:
            if exception is None or errored is None:
                raise ArgumentError('export endpoint or exception/errorED must not be null')
            self.__importref = ImportReference.fromexception(exception, errored)
            self.__rsa = None
        else:
            self.__rsa = endpoint._rsa()
            endpoint._add_import_registration(self)   
            self.__importref = ImportReference.fromendpoint(endpoint)
        self.__closed = False
        self.__lock = threading.RLock()
    
    def _import_endpoint(self):
        with self.__lock:
            return None if self.__closed else self.__importref._importendpoint()
         
    def _matched(self,ed):
        with self.__lock:
            return False if self.__closed else self.__importref._matched(ed)

    def _importreference(self):
        with self.__lock:
            return None if self.__closed else self.__importref

    def importerid(self):
        with self.__lock:
            return None if self.__closed else self.__importref.importerid()
        
    def reference(self):
        with self.__lock:
            return None if self.__closed else self.__importref.reference()
    
    def exception(self):
        with self.__lock:
            return None if self.__closed else self.__importref.exception()
    
    def description(self):
        with self.__lock:
            return None if self.__closed else self.__importref.description()
    
    def close(self):
        publish = False
        providerid = None
        exception = None
        imRef = None
        ed = None
        with self.__lock:
            if not self.__closed:
                providerid = self.__importref.importerid()
                exception = self.__importref.exception()
                imRef = self.__importref
                ed = self.__importref.description()
                publish = self.__importref.close(self)
                self.__importref = None
                self.__closed = True
        if publish and imRef and self.__rsa:
            self.__rsa._publish_event(RemoteServiceAdminEvent.fromimportunreg(self.__rsa._get_bundle(), providerid, imRef, exception, ed))
            self.__rsa = None    
                    
class _ExportEndpoint(object):
    
    def __init__(self, rsa, exporter, ed, svc_ref):
        self.__rsa = rsa
        self.__exporter = exporter
        self.__ed = ed
        self.__svc_ref = svc_ref
        self.__lock = threading.RLock()
        self.__active_registrations = []
        
    def _rsa(self):
        with self.__lock:
            return self.__rsa
    
    def _originalprops(self):
        with self.__lock:
            return self.reference().get_properties()
        
    def _add_export_registration(self, export_reg):
        with self.__lock:
            self.__active_registrations.append(export_reg)
    
    def _remove_export_registration(self, export_reg):
        with self.__lock:
            self.__active_registrations.remove(export_reg) 
                   
    def description(self):
        with self.__lock:
            return self.__ed
        
    def reference(self):
        with self.__lock:
            return self.__svc_ref
    
    def exporterid(self):
        with self.__lock:
            return self.__exporter.get_id()
    
    def update(self, props):
        with self.__lock:
            srprops = self.reference.get_properties().copy()
            rsprops = self.__orig_props.copy()
            updateprops = rsprops if props is None else props.update(rsprops).copy()
            updatedprops = updateprops.update(srprops).copy()
            updatedprops[rsa.ECF_ENDPOINT_TIMESTAMP] = rsa.get_current_time_millis()
            self.__ed = EndpointDescription(updatedprops)
            return self.__ed

    def close(self, export_reg):
        with self.__lock:
            try:
                self.__active_registrations.remove(export_reg)
            except ValueError:
                return False
            if len(self.__active_registrations) is 0:
                removed = False
                try:
                    removed = self.__exporter.unexport_service(self.__ed)
                except Exception as e:
                    _logger.error(e)
                    return False
                if removed:
                    try:
                        self.__rsa._remove_exported_service(export_reg)
                    except Exception as e:
                        _logger.error(e)
                        return False
                    self.__ed = None
                    self.__exporter = None
                    self.__svc_ref = None
                    self.__rsa = None
                    return True
        return False
    
class ExportReference(object):
    
    @classmethod
    def fromendpoint(cls,endpoint):
        return cls(endpoint=endpoint)
    
    @classmethod
    def fromexception(cls,e,errored):
        return cls(endpoint=None,exception=e,errored=errored)
    
    def __init__(self,endpoint=None,exception=None,errored=None):
        self.__lock = threading.RLock()
        if endpoint is None:
            if exception is None or errored is None:
                raise ArgumentError('Must supply either endpoint or throwable/errorEndpointDescription')
            self.__exception = exception
            self.__errored = errored
            self.__endpoint = None
        else:
            self.__endpoint = endpoint
            self.__exception = None
            self.__errored = None
    
    def exporterid(self):
        with self.__lock:
            return None if self.__endpoint is None else self.__endpoint.exporterid()
    
    def reference(self):
        with self.__lock:
            return None if self.__endpoint is None else self.__endpoint.reference()
    
    def description(self):
        with self.__lock:
            return None if self.__endpoint is None else self.__endpoint.description()
    
    def exception(self):
        return self.__exception

    def update(self,properties):
        with self.__lock:
            return None if self.__endpoint is None else self.__endpoint.update(properties)
        
    def close(self,export_reg):
        with self.__lock:
            if self.__endpoint is None:
                return False
            else:
                result = self.__endpoint.close(export_reg)
                self.__endpoint = None
                return result
            
class ExportRegistration(object):

    @classmethod
    def fromreg(cls, export_reg):
        return cls(export_reg.__rsa,export_reg.__export_ref.exportendpoint)
    
    @classmethod
    def fromendpoint(cls, rsa, exporter, ed, svc_ref):
        return cls(rsa,_ExportEndpoint(rsa, exporter, ed, svc_ref))
    
    @classmethod
    def fromexception(cls,exception,errored):
        return cls(rsa=None,endpoint=None,exception=exception,errored=errored)
    
    def __init__(self,rsa=None,endpoint=None,exception=None,errored=None):
        if endpoint is None:
            if exception is None or errored is None:
                raise ArgumentError('export endpoint or exception/errorED must not be null')
            self.__exportref = ExportReference.fromexception(exception, errored)
            self.__rsa = None
        else:
            self.__rsa = endpoint._rsa()
            endpoint._add_export_registration(self)   
            self.__exportref = ExportReference.fromendpoint(endpoint)
        self.__closed = False
        self.__updateexception = None
        self.__lock = threading.RLock()
        
    def _match(self,sr,cid=None):
        with self.__lock:
            oursr = self.reference()
            if oursr is None:
                return False
            srcompare = oursr == sr
            if cid is None:
                return srcompare
            ourcid = self.containerid()
            if ourcid is None:
                return False
            return srcompare and ourcid == cid
    
    def _exportreference(self):
        with self.__lock:
            return None if self.__closed else self.__exportref

    def _exportendpoint(self,sr,cid):
        with self.__lock:
            return None if self.__closed else self.__exportref.exportendpoint if self._match(sr,cid) else None

    def exporterid(self):
        with self.__lock:
            return None if self.__closed else self.__exportref.exporterid()

    def reference(self):
        with self.__lock:
            return None if self.__closed else self.__exportref.reference()
    
    def exception(self):
        with self.__lock:
            return self.__updateexception if self.__closed else self.__exportref.exception()
    
    def description(self):
        with self.__lock:
            return None if self.__closed else self.__exportref.description()
    
    def close(self):
        publish = False
        providerid = None
        exception = None
        exRef = None
        ed = None
        with self.__lock:
            if not self.__closed:
                providerid = self.__exportref.exporterid()
                exception = self.__exportref.exception()
                ed = self.__exportref.description()
                exRef = self.__exportref
                publish = self.__exportref.close(self)
                self.__exportref = None
                self.__closed = True
        if publish and exRef and self.__rsa:
            self.__rsa._publish_event(RemoteServiceAdminEvent.fromexportunreg(self.__rsa._get_bundle(), providerid, exRef, exception, ed))
            self.__rsa = None

@ComponentFactory('pelix-rsa-remoteserviceadmin-factory')
@Provides(rsa.REMOTE_SERVICE_ADMIN)
@Requires('_exporters', rsa.SERVICE_EXPORT_PROVIDER, True, True)
@Requires('_importers', rsa.SERVICE_IMPORT_PROVIDER, True, True)
@Requires('_rsa_event_listeners', rsa.RSA_EVENT_LISTENER, True, True)
@Instantiate(rsa.REMOTE_SERVICE_ADMIN)
class RemoteServiceAdmin(object):
    
#    def __setattr__(self, *args, **kwargs):
#        if args[0] == '_exporters':
#            print("setattr args="+str(args)+",kwargs="+str(kwargs))
#            print(''.join(format_stack()))
#        return object.__setattr__(self, *args, **kwargs)
    '''
    iPopo implementation of RemoteServiceAdmin service specified by Chapter 122 in 
    the OSGi Enterprise specification chapter 122.  See https://www.osgi.org/developer/specifications/
    '''
    def get_exported_services(self):
        with self._exported_regs_lock:
            return self._exported_regs.copy()
    
    def get_imported_services(self):
        with self._imported_regs_lock:
            return self._imported_regs.copy()
    
    def export_service(self, svc_ref, overriding_props = None):
            if not svc_ref:
                raise ArgumentError('svc_ref param must not be empty')
            assert isinstance(svc_ref,ServiceReference)
            
            intfs = rsa.get_exported_interfaces(svc_ref, overriding_props)
            if not intfs:
                raise ArgumentError(rsa.SERVICE_EXPORTED_INTERFACES+' must be set in svc_ref properties or overriding_props')
        
            export_props = svc_ref.get_properties().copy()
            if overriding_props:
                export_props.update(overriding_props)
            
            configs = export_props[rsa.SERVICE_EXPORTED_CONFIGS]
            if not configs:
                raise ArgumentError(rsa.SERVICE_EXPORTED_CONFIGS+' must be set in svc_ref or overriding properties')
            
            # find exporters that handle configs
            exporters = [exporter for exporter in self._exporters[:]
                 if exporter.handles(configs)]  
            
            errorprops = rsa.get_edef_props_error(svc_ref.get_property('objectClass'))
            errored = EndpointDescription(svc_ref, errorprops)
            result_regs = []
            result_events = []
            if len(exporters) == 0:
                _logger.warning("No exporter for %s", configs)
                error_reg = ExportRegistration.fromexception(SelectExporterError('No exporter for '+str(configs)), errored)
                self._add_exported_service(error_reg)
                result_regs.append(error_reg)
            
            if len(result_regs) == 0:     
                with self._exported_regs_lock:
                    for exporter in exporters:
                        found_regs = []
                        exporterid = exporter.get_id()
                        for reg in self._exported_regs:
                            if reg._match(svc_ref,exporterid):
                                found_regs.append(reg)
                        #if so then found_regs will be non-empty
                        if len(found_regs) > 0:
                            for found_reg in found_regs:
                                new_reg = ExportRegistration.fromreg(self, found_reg)
                                self._add_exported_service(new_reg)
                                result_regs.append(new_reg)
                        
                        if len(result_regs) == 0:
                            # Now we actually export
                            export_reg = None
                            event = None
                            try:
                                ed_props = exporter.make_endpoint_props(intfs, svc_ref, export_props)
                                errored = EndpointDescription.fromprops(ed_props)
                            except Exception as e:
                                export_reg = ExportRegistration.fromexception(e, errored)
                            if not export_reg:
                                try:
                                    export_ed = exporter.export_service(svc_ref, ed_props)
                                    export_reg = ExportRegistration.fromendpoint(self, exporter, export_ed, svc_ref)
                                    event = RemoteServiceAdminEvent.fromexportreg(self._get_bundle(), export_reg)
                                except Exception as e:
                                    export_reg = ExportRegistration.fromexception(e, errored)
                                    event = RemoteServiceAdminEvent.fromexporterror(self._get_bundle(), export_reg.exporterid(), export_reg.exception()), export_reg.description(())
                            self._add_exported_service(export_reg)
                            result_regs.append(export_reg)
                            result_events.append(event)
                #publish events
                for e in result_events:
                    self._publish_event(e)    
            return result_regs
            
    def import_service(self, endpoint_description):
        if not endpoint_description:
                raise ArgumentError(None,'endpoint_description param must not be empty')
        assert isinstance(endpoint_description,EndpointDescription)

        remote_configs = rsa.get_string_plus_property(rsa.REMOTE_CONFIGS_SUPPORTED, endpoint_description.get_properties(), None)
        if not remote_configs:
            raise ArgumentError(None,'endpoint_description must contain '+rsa.REMOTE_CONFIGS_SUPPORTED+" property")
        
        if len(self._importers) == 0:
            return ImportRegistration.fromexception(SelectImporterError('Could not find importer for exported_configs='+str(remote_configs)), endpoint_description)

        # find exporters that handle configs
        importer = None
        for imp in self._importers:
            if imp.handles(remote_configs):
                importer = imp
                break
            
        if importer:    
            with self._imported_regs_lock:
                export_props = None
                found_reg = None
                for reg in self._imported_regs:
                    if reg._matched(endpoint_description):
                        found_reg.append(reg)
                if found_reg:
                    new_reg = None
                    #if so then found_regs will be non-empty
                    ex = found_reg.exception()
                    if ex:
                        new_reg = ImportRegistration.fromexception(ex, endpoint_description)
                    else:
                        new_reg = ImportRegistration.fromreg(self, found_reg)
                    self._add_imported_service(new_reg)
                    return new_reg

                import_reg = None
                event = None
                try:
                    export_props = importer.make_proxy_props(endpoint_description)
                    svc_reg = importer.import_service(endpoint_description, export_props)
                    import_reg = ImportRegistration.fromendpoint(self, importer, endpoint_description, svc_reg)
                    event = RemoteServiceAdminEvent.fromimportreg(self._get_bundle(), import_reg)
                except Exception as e:
                    import_reg = ImportRegistration.fromexception(e, endpoint_description)
                    event = RemoteServiceAdminEvent.fromimporterror(self._get_bundle(), import_reg.importerid(), import_reg.exception()), import_reg.description(())
                self._imported_regs.append(import_reg)
                self._publish_event(event)
                return import_reg

    def __init__(self):
        """
        Sets up the component
        """
        # Bundle context
        self._context = None

        self._exported_regs = []
        self._exported_regs_lock = threading.RLock()
      
        self._imported_regs = []
        self._imported_regs_lock = threading.RLock()
        
        self._rsa_event_listeners = []
        
            
    def _publish_event(self,event):
        listeners = self._rsa_event_listeners
        for l in listeners:
            try:
                l.remote_admin_event(event)
            except Exception as e:
                _logger.error(e)
    
    def _get_bundle(self):
        if self._context:
            return self._context.get_bundle()
        return None

    @Validate
    def _validate(self, context):
        """
        Component validated
        """
        # Get the framework UID
        self._fw_uid = context.get_property(pelix.constants.FRAMEWORK_UID)
        self._context = context
   
    @Invalidate
    def _invalidate(self, context):
        """
        Component invalidated: clean up storage
        """
        with self._exported_regs_lock:
            for reg in self._exported_regs:
                reg.close()
            self._exported_regs.clear()
        with self._imported_regs_lock:
            for reg in self._imported_regs:
                reg.close()
                self._imported_regs.clear()
                
        self._context = None
        
    @BindField('_importers')
    def _bind_importer(self, field, importer, svc_ref):
        importer.bound()
        
    @UnbindField('_importers')
    def _unbind_importer(self, field, importer, svc_ref):
        importer.unbound()

    @BindField('_exporters')
    def _bind_exporter(self, field, exporter, svc_ref):
        exporter.bound()
        
    @UnbindField('_exporters')
    def _unbind_exporter(self, field, exporter, svc_ref):
        exporter.unbound()
        
    def _unexport_service(self,svc_ref):
        with self._exported_regs_lock:
            for reg in self._exported_regs:
                if reg._match(svc_ref,None):
                    reg.close()
    
    def _valid_exported_interfaces(self,svc_ref,intfs):    
        if intfs is None or len(intfs) == 0:
            return False
        object_class = svc_ref.get_property(constants.OBJECTCLASS)
        for item in intfs:
            if not item in object_class:
                return False
        return True
    
    def _find_existing_export_endpoint(self, svc_ref, cid):
        for er in self.__exported_registrations:
            if er._match(svc_ref,cid):
                return er
        return None
    
    def _add_exported_service(self,export_reg):
        with self._exported_regs_lock:
            self._exported_regs.append(export_reg)
    
    def _remove_exported_service(self,export_reg):
        with self._exported_regs_lock:
            self._exported_regs.remove(export_reg)

    def _add_imported_service(self,import_reg):
        with self._imported_regs_lock:
            self._imported_regs.append(import_reg)
    
    def _remove_imported_service(self,import_reg):
        with self._imported_regs_lock:
            self._imported_regs.remove(import_reg)
                   
        

class AbstractRpcServiceExporter(object):
    """
    Abstract Remote Services exporter
    """
    def __init__(self):
        """
        Sets up the exporter
        """
        # Bundle context
        self._context = None        
        self._framework_uid = None
        # id
        self._id = None        
        # exported configs
        self._exported_configs = None
        # intents
        self._intents = None
        # namespace
        self._namespace = None
        
    def get_id(self):
        return self._id
    
    @Validate
    def validate(self, context):
        """
        Component validated
        """
        # Store the context
        self._context = context
        self._framework_uid = rsa.get_fw_uuid(self._context)

    @Invalidate
    def invalidate(self, context):
        """
        Component invalidated
        """
        # Clean up members
        self._context = None
        self._framework_uid = None

    def handles(self, configurations):
        """
        Checks if this provider handles the given configuration types

        :param configurations: Configuration types
        """
        if configurations is None or self._exported_configs is None:
            return False
        
        return len([itm for itm in self._exported_configs if itm in rsa.get_string_plus_property_value(configurations)]) > 0

    def bound(self):
        pass
    
    def unbound(self):
        pass
    
    def _export_service(self,svc,ed_props):
        return None

    def _update_service(self, ed):
        return False
    
    def _unexport_service(self, ed):
        return False
    
    def _make_endpoint_extra_props(self, export_props):
        return {}
    
    def make_endpoint_props(self, intfs, svc_ref, export_props):
        pkg_vers = rsa.get_package_versions(intfs, export_props)
        rsa_props = rsa.get_rsa_props(intfs, self._exported_configs, self._intents, svc_ref.get_property(constants.SERVICE_ID), self._framework_uid, pkg_vers)
        ecf_props = rsa.get_ecf_props(self.get_id(), self._namespace, rsa.get_next_rsid(), rsa.get_current_time_millis())
        extra_props = rsa.get_extra_props(export_props)
        exporter_props = self._make_endpoint_extra_props(export_props)
        return rsa.merge_dicts(rsa_props, ecf_props, extra_props, exporter_props)
    
    def export_service(self, svc_ref, export_props):
        self._export_service(self._context.get_service(svc_ref), export_props.copy())
        return EndpointDescription.fromprops(export_props)

    def update_service(self, ed):
        assert isinstance(ed, EndpointDescription)
        return self._update_service(ed)

    def unexport_service(self, ed):
        assert isinstance(ed, EndpointDescription)
        return self._unexport_service(ed)

class AbstractRpcServiceImporter(object):
    """
    Abstract Remote Services importer
    """
    def __init__(self):
        """
        Sets up the importer
        """
        # Bundle context
        self._context = None        
        # supported configs
        self._supported_configs = None
        # namespace
        self._namespace = None
        self.__registrations = {}
        self.__lock = RLock()
        self._id = None
        
    def get_id(self):
        return self._id

    @Validate
    def validate(self, context):
        """
        Component validated
        """
        # Store the context
        self._context = context
        if not self._id:
            self._id = rsa.create_uuid_uri()
        
    @Invalidate
    def invalidate(self, context):
        """
        Component invalidated
        """
        # Unregister all of our services
        with self.__lock:
            for svc_reg in self.__registrations.values():
                svc_reg.unregister()

        # Clean up members
        self.__registrations.clear()
        self._context = None
        self._id = None

    def handles(self, configurations):
        """
        Checks if this provider handles the given configuration types

        :param configurations: Remote Configuration types
        """
        if configurations is None or self._supported_configs is None:
            return False
        
        return len([itm for itm in self._supported_configs if itm in rsa.get_string_plus_property_value(configurations)]) > 0
    
    def make_proxy_props(self, ed):
        props = ed.get_properties()
        result = rsa.get_extra_props(props)
        svc_intents = rsa.get_string_plus_property_value(ed.get_intents())
        if svc_intents:
            result[rsa.SERVICE_INTENTS] = svc_intents
        
        #XXX this could be extended for ecf
        result[rsa.SERVICE_IMPORTED] = True
        
        result[rsa.SERVICE_EXPORTED_CONFIGS] = self._supported_configs
        
        result[rsa.ENDPOINT_ID] = ed.get_id()
        return result
        
    def get_service_proxy(self, ed):
        raise NotImplementedError("get_service_proxy must be implemented by AbstractRpcServiceImporter subclass")
    
    def unget_service_proxy(self, ed):
        raise NotImplementedError("unget_service_proxy must be implemented by AbstractRpcServiceImporter subclass")

    def bound(self):
        pass
    
    def unbound(self):
        pass
    
    def get_registration(self, endpointid):
        with self.__lock:
            try:
                return self.__registrations[endpointid]
            except KeyError:
                return None
    
    def import_service(self, ed, proxy_props):
        with self.__lock:
            proxy = self.get_service_proxy(ed)
            reg = self._context.register_service(ed.get_interfaces(),proxy,proxy_props)
            self.__registrations[ed.get_id()] = reg
            return reg            
            
    def update_service(self, ed, new_props):
        with self.__lock:
            reg = None
            try:
                reg = self.get_registration(ed.get_id())
            except KeyError:
                pass
            if reg:
                reg.set_properties(new_props)
                return True
            else:
                return False
                
    def unimport_service(self, ed):
        with self.__lock:
            reg = None
            try:
                reg = self.__registrations.pop(ed.get_id(), None)
            except KeyError:
                pass
            if reg:
                self.unget_service_proxy(ed)
                reg.unregister()
                return True
            else:
                return False

class EndpointEvent(object):
    
    ADDED = 1
    REMOVED = 2
    MODIFIED = 4
    MODIFIED_ENDMATCH = 8
    
    def __init__(self,typ,ed):
        self._type = typ
        self._ed = ed
    
    def get_type(self):
        return self._type
    
    def get_endpoint(self):
        return self._ed

@Provides(rsa.ENDPOINT_EVENT_LISTENER)    
class EndpointEventListener(object):
    
    ENDPOINT_LISTENER_SCOPE = 'endpoint.listener.scope'
    
    def endpoint_changed(self, ep_event, matched_scope):
        pass
    
class RemoteServiceAdminEvent(object):
    
    IMPORT_REGISTRATION = 1
    EXPORT_REGISTRATION = 2
    EXPORT_UNREGISTRATION = 3
    IMPORT_UNREGISTRATION = 4
    IMPORT_ERROR = 5
    EXPORT_ERROR = 6
    EXPORT_WARNING = 7
    IMPORT_WARNING = 8
    IMPORT_UPDATE = 9
    EXPORT_UPDATE = 10
    
    @classmethod
    def fromimportreg(cls,bundle,import_reg):
        return RemoteServiceAdminEvent(RemoteServiceAdminEvent.IMPORT_REGISTRATION,bundle,import_reg.importerid(),import_ref=import_reg._importreference(),ed=import_reg.description())
    @classmethod
    def fromexportreg(cls,bundle,export_reg):
        return RemoteServiceAdminEvent(RemoteServiceAdminEvent.EXPORT_REGISTRATION,bundle,export_reg.exporterid(),export_ref=export_reg._exportreference(),ed=export_reg.description())

    @classmethod
    def fromimportunreg(cls,bundle,providerid,import_ref,exception,ed):
        return RemoteServiceAdminEvent(RemoteServiceAdminEvent.IMPORT_UNREGISTRATION,bundle,providerid,import_ref=import_ref,ed=ed)
    @classmethod
    def fromexportunreg(cls,bundle,providerid,export_ref,exception,ed):
        return RemoteServiceAdminEvent(RemoteServiceAdminEvent.EXPORT_UNREGISTRATION,bundle,providerid,export_ref=export_ref,ed=ed)

    @classmethod
    def fromimporterror(cls, bundle, providerid, exception, ed):
        return RemoteServiceAdminEvent(RemoteServiceAdminEvent.IMPORT_ERROR,bundle,providerid,exception=exception,ed=ed)
    @classmethod
    def fromexporterror(cls, bundle, providerid, exception, ed):
        return RemoteServiceAdminEvent(RemoteServiceAdminEvent.EXPORT_ERROR,bundle,providerid,exception=exception,ed=ed)

    def __init__(self,typ,bundle,providerid,import_ref=None,export_ref=None,exception=None,ed=None):
        self._type = typ
        self._bundle = bundle
        self._providerid = providerid
        self._import_ref = import_ref
        self._export_ref = export_ref
        self._exception = exception
        self._ed = ed
    
    def get_description(self):
        return self._ed
    
    def get_providerid(self):
        return self._providerid
    
    def get_type(self):
        return self._type
    
    def get_source(self):
        return self._bundle
    
    def get_import_ref(self):
        return self._import_ref
    
    def get_export_ref(self):
        return self._export_ref
    
    def get_exception(self):
        return self._exception
    
class RemoteServiceAdminEventListener(object):
    
    def remote_admin_event(self, event):
        pass
    
@ComponentFactory('pelix-rsa-remoteserviceadmin-tm-factory')
@Provides(rsa.RSA_EVENT_LISTENER)
@Instantiate('pelix-rsa-remoteserviceadmin-tm')
class DebugRemoteServiceAdminEventListener(RemoteServiceAdminEventListener):
        def remote_admin_event(self, event):
            print("rsa event.  type="+str(event.get_type()))

    