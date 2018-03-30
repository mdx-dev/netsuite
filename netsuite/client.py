import logging
import re
from functools import wraps
from typing import Callable, Dict, List, Sequence, Union

import requests
import zeep
from zeep.cache import SqliteCache

from . import passport
from .config import Config
from .util import cached_property

logger = logging.getLogger(__name__)


def WebServiceCall(path: str = None, extract: Callable = None) -> Callable:
    """
    Decorator for NetSuite methods returning SOAP responses

    Args:
        path:
            A dot-separated path for specifying where relevant data resides
        extract:
            A function to extract data from response before returning it

    Returns:
        Decorator to use on `NetSuite` methods
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(self, *args, **kw):
            response = fn(self, *args, **kw)

            if path is not None:
                for part in path.split('.'):
                    response = getattr(response, part)

            if extract is not None:
                response = extract(response)

            return response
        return wrapper
    return decorator


class NetSuite:
    sandbox = True
    version = '2017.2.0'
    wsdl_url_tmpl = 'https://webservices.{subpath}netsuite.com/wsdl/v{underscored_version}/netsuite.wsdl'

    def __repr__(self) -> str:
        return f'<NetSuite {self.hostname}({self.version})>'

    def __init__(
        self,
        config: Union[Config, Dict],
        *,
        sandbox: bool = None,
        version: str = None,
        wsdl_url: str = None,
        cache: zeep.cache.Base = None,
        session: requests.Session = None,
    ) -> None:
        if sandbox is not None:
            self.sandbox = sandbox

        if version is not None:
            assert re.match(r'\d+\.\d+\.\d+', version)
            self.version = version

        self.__config = self._make_config(config)
        self.__wsdl_url = wsdl_url
        self.__cache = cache
        self.__session = session

    @cached_property
    def wsdl_url(self) -> str:
        return self.__wsdl_url or self._generate_wsdl_url()

    @cached_property
    def cache(self) -> zeep.cache.Base:
        return self.__cache or self._generate_cache()

    @cached_property
    def session(self) -> requests.Session:
        return self.__session or self._generate_session()

    @cached_property
    def client(self) -> zeep.Client:
        return self._generate_client()

    @cached_property
    def transport(self):
        return self._generate_transport()

    @property
    def config(self) -> Config:
        return self.__config

    @cached_property
    def hostname(self) -> str:
        return self.wsdl_url.replace('https://', '').partition('/')[0]

    @property
    def service(self) -> zeep.client.ServiceProxy:
        return self.client.service

    def _make_config(
        self,
        values_obj: Dict,
    ) -> Config:
        if isinstance(values_obj, Config):
            return values_obj
        return Config(**values_obj)

    @property
    def underscored_version(self) -> str:
        return self.version.replace('.', '_')

    @property
    def underscored_version_no_micro(self) -> str:
        return self.underscored_version.rpartition('_')[0]

    def _generate_wsdl_url(self) -> str:
        return self.wsdl_url_tmpl.format(
            underscored_version=self.underscored_version,
            subpath='sandbox.' if self.sandbox else '',
        )

    def _generate_cache(self) -> zeep.cache.Base:
        return SqliteCache(timeout=60 * 60 * 24 * 365)

    def _generate_session(self) -> requests.Session:
        return requests.Session()

    def _generate_transport(self) -> zeep.transports.Transport:
        return zeep.transports.Transport(
            session=self.session,
            cache=self.cache,
        )

    def generate_passport(self) -> Dict[str, zeep.xsd.Element]:
        return passport.make(self.client, self.config)

    def _set_default_soapheaders(self, client: zeep.Client) -> None:
        client.set_default_soapheaders({
            # https://netsuite.custhelp.com/app/answers/detail/a_id/40934
            # 'preferences': {
            #     'warningAsError': True/False,
            #     'disableMandatoryCustomFieldValidation': True/False,
            #     'disableSystemNotesForCustomFields': True/False,
            #     'ignoreReadOnlyFields': True/False,
            #     'runServerSuiteScriptAndTriggerWorkflows': True/False,
            # },
            # TODO: Add ability to re-generate OAuth token for each use of the
            #       TokenPassport. In the meantime it has to be passed in to
            #       every service request like this:
            #           `_soapheaders=self.generate_passport()`
            # }, **self.generate_passport())
        })

    def _generate_client(self) -> zeep.Client:
        c = zeep.Client(
            self.wsdl_url,
            transport=self.transport,
        )
        self._set_default_soapheaders(c)
        return c

    def _get_namespace(self, name: str, sub_namespace: str) -> str:
        return (
            'urn:{name}_{version}.{sub_namespace}.webservices.netsuite.com'
            .format(
                name=name,
                version=self.underscored_version_no_micro,
                sub_namespace=sub_namespace,
            )
        )

    def _type_factory(
        self,
        name: str,
        sub_namespace: str,
    ) -> zeep.client.Factory:
        return self.client.type_factory(
            self._get_namespace(name, sub_namespace)
        )

    @cached_property
    def Core(self) -> zeep.client.Factory:
        return self._type_factory('core', 'platform')

    @cached_property
    def CoreTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.core', 'platform')

    @cached_property
    def FaultsTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.faults', 'platform')

    @cached_property
    def Faults(self) -> zeep.client.Factory:
        return self._type_factory('faults', 'platform')

    @cached_property
    def Messages(self) -> zeep.client.Factory:
        return self._type_factory('messages', 'platform')

    @cached_property
    def Common(self) -> zeep.client.Factory:
        return self._type_factory('common', 'platform')

    @cached_property
    def CommonTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.common', 'platform')

    @cached_property
    def Scheduling(self) -> zeep.client.Factory:
        return self._type_factory('scheduling', 'activities')

    @cached_property
    def SchedulingTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.scheduling', 'activities')

    @cached_property
    def Communication(self) -> zeep.client.Factory:
        return self._type_factory('communication', 'general')

    @cached_property
    def CommunicationTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.communication', 'general')

    @cached_property
    def Filecabinet(self) -> zeep.client.Factory:
        return self._type_factory('filecabinet', 'documents')

    @cached_property
    def FilecabinetTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.filecabinet', 'documents')

    @cached_property
    def Relationships(self) -> zeep.client.Factory:
        return self._type_factory('relationships', 'lists')

    @cached_property
    def RelationshipsTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.relationships', 'lists')

    @cached_property
    def Support(self) -> zeep.client.Factory:
        return self._type_factory('support', 'lists')

    @cached_property
    def SupportTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.support', 'lists')

    @cached_property
    def Accounting(self) -> zeep.client.Factory:
        return self._type_factory('accounting', 'lists')

    @cached_property
    def AccountingTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.accounting', 'lists')

    @cached_property
    def Sales(self) -> zeep.client.Factory:
        return self._type_factory('sales', 'transactions')

    @cached_property
    def SalesTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.sales', 'transactions')

    @cached_property
    def Purchases(self) -> zeep.client.Factory:
        return self._type_factory('purchases', 'transactions')

    @cached_property
    def PurchasesTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.purchases', 'transactions')

    @cached_property
    def Customers(self) -> zeep.client.Factory:
        return self._type_factory('customers', 'transactions')

    @cached_property
    def CustomersTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.customers', 'transactions')

    @cached_property
    def Financial(self) -> zeep.client.Factory:
        return self._type_factory('financial', 'transactions')

    @cached_property
    def FinancialTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.financial', 'transactions')

    @cached_property
    def Bank(self) -> zeep.client.Factory:
        return self._type_factory('bank', 'transactions')

    @cached_property
    def BankTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.bank', 'transactions')

    @cached_property
    def Inventory(self) -> zeep.client.Factory:
        return self._type_factory('inventory', 'transactions')

    @cached_property
    def InventoryTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.inventory', 'transactions')

    @cached_property
    def General(self) -> zeep.client.Factory:
        return self._type_factory('general', 'transactions')

    @cached_property
    def Customization(self) -> zeep.client.Factory:
        return self._type_factory('customization', 'setup')

    @cached_property
    def CustomizationTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.customization', 'setup')

    @cached_property
    def Employees(self) -> zeep.client.Factory:
        return self._type_factory('employees', 'lists')

    @cached_property
    def EmployeesTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.employees', 'lists')

    @cached_property
    def Website(self) -> zeep.client.Factory:
        return self._type_factory('website', 'lists')

    @cached_property
    def WebsiteTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.website', 'lists')

    @cached_property
    def EmployeesTransactions(self) -> zeep.client.Factory:
        return self._type_factory('employees', 'transactions')

    @cached_property
    def EmployeesTransactionsTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.employees', 'transactions')

    @cached_property
    def Marketing(self) -> zeep.client.Factory:
        return self._type_factory('marketing', 'lists')

    @cached_property
    def MarketingTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.marketing', 'lists')

    @cached_property
    def DemandPlanning(self) -> zeep.client.Factory:
        return self._type_factory('demandplanning', 'transactions')

    @cached_property
    def DemandPlanningTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.demandplanning', 'transactions')

    @cached_property
    def SupplyChain(self) -> zeep.client.Factory:
        return self._type_factory('supplychain', 'lists')

    @cached_property
    def SupplyChainTypes(self) -> zeep.client.Factory:
        return self._type_factory('types.supplychain', 'lists')

    def request(
        self,
        service_name: str,
        *args,
        **kw
    ) -> zeep.xsd.ComplexType:
        """
        Make a web service request to NetSuite

        Args:
            service_name:
                The NetSuite service to call
        Returns:
            The response from NetSuite
        """
        svc = getattr(self.service, service_name)
        return svc(*args, _soapheaders=self.generate_passport(), **kw)

    @WebServiceCall(
        'body.readResponseList.readResponse',
        extract=lambda resp: [r['record'] for r in resp],
    )
    def getList(
        self,
        recordType: str,
        *,
        internalIds: Sequence[int] = (),
        externalIds: Sequence[str] = (),
    ) -> List[Dict]:
        """Get a list of records"""
        assert internalIds or externalIds
        return self.request(
            'getList',
            self.Messages.GetListRequest(
                baseRef=[
                    self.Core.RecordRef(
                        type=recordType,
                        internalId=internalId,
                    ) for internalId in internalIds
                ] + [
                    self.Core.RecordRef(
                        type=recordType,
                        externalId=externalId,
                    ) for externalId in externalIds
                ],
            )
        )

    @WebServiceCall(
        'body.getItemAvailabilityResult.itemAvailabilityList.itemAvailability'
    )
    def getItemAvailability(
        self,
        *,
        internalIds: Sequence[int] = (),
        externalIds: Sequence[str] = (),
    ) -> List[Dict]:
        assert internalIds or externalIds
        return self.request(
            'getItemAvailability',
            itemAvailabilityFilter={
                'item': [
                    {
                        'recordRef': {
                            'type': 'inventoryItem', 'internalId': internalId,
                        },
                    } for internalId in internalIds
                ] + [
                    {
                        'recordRef': {
                            'type': 'inventoryItem', 'externalId': externalId,
                        },
                    } for externalId in externalIds
                ],
            },
        )