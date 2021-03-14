"""TOPdesk integration for Cortex XSOAR"""

import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *

import os
import math
import shutil
import urllib3
import basicauth
import traceback
import dateparser

from typing import Any, Dict, List, Optional, Callable, Tuple, Union
from base64 import b64encode

# Disable insecure warnings
urllib3.disable_warnings()

''' CONSTANTS '''

INTEGRATION_NAME = 'TOPdesk'
XSOAR_ENTRY_TYPE = 'Automation'  # XSOAR
DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MAX_API_PAGE_SIZE = 10000

''' CLIENT CLASS '''


class Client(BaseClient):
    """Client class to interact with the TOPdesk service API"""

    def __init__(self, base_url, verify, headers, new_query):
        super().__init__(base_url=base_url, verify=verify, headers=headers)
        self._proxies = handle_proxy(proxy_param_name='proxy', checkbox_default_value=False)
        self.new_query = new_query

    def get_list_with_query(self, list_type: str, start: Optional[int] = None, page_size: Optional[int] = None,
                            query: Optional[str] = None, modification_date_start: Optional[str] = None,
                            modification_date_end: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of objects that support start, page_size and query arguments."""

        allowed_list_type = ["persons", "operators", "branches", "incidents"]
        if list_type not in allowed_list_type:
            raise ValueError(f"Cannot get list of type {list_type}.\n "
                             f"Only {allowed_list_type} are allowed.")

        url_suffix = f"/{list_type}"
        inline_parameters = False
        request_params: Dict[str, Any] = {}
        if start:
            url_suffix = f"{url_suffix}?start={start}"
            inline_parameters = True

        if page_size:
            if inline_parameters:
                url_suffix = f"{url_suffix}&page_size={page_size}"
            else:
                url_suffix = f"{url_suffix}?page_size={page_size}"
                inline_parameters = True

        if query:
            if list_type != "incidents" or self.new_query:
                query = f"query={query}"

            if inline_parameters:
                url_suffix = f"{url_suffix}&{query}"

            else:
                url_suffix = f"{url_suffix}?{query}"

        if modification_date_start:
            request_params["modification_date_start"] = modification_date_start

        if modification_date_end:
            request_params["modification_date_end"] = modification_date_end

        return self._http_request(
            method='GET',
            url_suffix=url_suffix,
            json_data=request_params
        )

    def get_list(self, endpoint: str) -> List[Dict[str, Any]]:
        """Get entry types using the API endpoint"""

        return self._http_request(
            method='GET',
            url_suffix=f"{endpoint}",
        )

    def get_single_endpoint(self, endpoint: str) -> Dict[str, Any]:
        """Get entry types using the API endpoint"""

        return self._http_request(
            method='GET',
            url_suffix=f"{endpoint}",
        )

    def create_incident(self, args: Dict[str, Any] = {}) -> Dict[str, Any]:
        """Create incident in TOPdesk"""

        if not args.get("caller", None):
            raise ValueError('Caller must be specified to create incident.')

        request_params = prepare_touch_request_params(args)

        return self._http_request(
            method='POST',
            url_suffix="/incidents/",
            json_data=request_params
        )

    def update_incident(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Update incident in TOPdesk"""

        if not args.get("id", None) and not args.get("number", None):
            raise ValueError('Either id or number must be specified to update incident.')

        if args.get("id", None):
            endpoint = f"/incidents/id/{args['id']}"
        else:
            endpoint = f"/incidents/number/{args['number']}"

        request_params = prepare_touch_request_params(args)

        return self._http_request(
            method='PUT',
            url_suffix=endpoint,
            json_data=request_params
        )

    def incident_do(self, action: str, incident_id: Optional[str], incident_number: Optional[str],
                    reason_id: Optional[str]) -> Dict[str, Any]:
        """Preform action on TOPdesk incident with specified reason_id if needed."""
        allowed_actions = ["escalate", "deescalate", "archive", "unarchive"]
        request_params: Dict[str, Any] = {}
        if action not in allowed_actions:
            raise ValueError(f'Endpoint {action} not in allowed endpoint list: {allowed_actions}')

        if not incident_id and not incident_number:
            raise ValueError('Either id or number must be specified to update incident.')

        if incident_id:
            endpoint = f"/incidents/id/{incident_id}"
        else:
            endpoint = f"/incidents/number/{incident_number}"

        if reason_id:
            request_params["id"] = reason_id

        return self._http_request(
            method='PUT',
            url_suffix=f"{endpoint}/{action}",
            json_data=request_params
        )

    def attachment_upload(self, incident_id: Optional[str], incident_number: Optional[str], file_entry: str,
                          file_name: str, invisible_for_caller: bool, file_description: Optional[str]):
        """Upload an attachment from file_entry to TOPdesk incident."""
        if not incident_id and not incident_number:
            raise ValueError('Either id or number must be specified to update incident.')

        if incident_id:
            endpoint = f"/incidents/id/{incident_id}"
        else:
            endpoint = f"/incidents/number/{incident_number}"

        request_params: Dict[str, Any] = {}
        request_params["invisibleForCaller"] = invisible_for_caller
        if file_description:
            request_params["description"] = file_description

        shutil.copyfile(demisto.getFilePath(file_entry)['path'], file_name)
        try:
            files = {'file': open(file_name, 'rb')}
            response = self._http_request(method='POST',
                                          url_suffix=f"{endpoint}/attachments",
                                          files=files,
                                          data=request_params)
        except Exception as e:
            os.remove(file_name)
            raise e
        os.remove(file_name)
        return response

    def add_filter_to_query(self, query: Optional[str], filter_name: str, filter_arg: str) -> Optional[str]:
        """Enhance query to include filter argument. Consider the supported query type."""
        if filter_name and filter_arg:
            if query:
                query = f"{query}&"
            else:
                query = ''

            if self.new_query:
                query = f"{query}{filter_name}=={filter_arg}"
            else:
                query = f"{query}{filter_name}={filter_arg}"

        return query


''' HELPER FUNCTIONS '''


def prepare_touch_request_params(args: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare request parameters for incident-create and  incident-update commands."""
    request_params: Dict[str, Any] = {}
    if args.get("entry_type", None):
        request_params["entryType"] = {"name": args["entry_type"]}
    else:
        request_params["entryType"] = {"name": XSOAR_ENTRY_TYPE}

    optional_params = ["caller", "status", "description", "request", "action",
                       "action_invisible_for_caller", "call_type", "category", "subcategory",
                       "external_number", "main_incident"]
    optional_named_params = ["call_type", "category", "subcategory"]
    if args:
        for optional_param in optional_params:
            if args.get(optional_param, None):
                if optional_param == "description":
                    request_params["briefDescription"] = args.get(optional_param, None)

                elif optional_param == "caller":
                    if args.get("registered_caller", False):
                        request_params["callerLookup"] = {"id": args[optional_param]}
                    else:
                        request_params["caller"] = {"dynamicName": args[optional_param]}

                elif optional_param in optional_named_params:
                    request_params[half_camelize(optional_param)] = {"name": args[optional_param]}
                else:
                    request_params[half_camelize(optional_param)] = args.get(optional_param, None)

    if args.get("additional_params", None):
        request_params.update(args["additional_params"])

    return request_params


def half_camelize(s: str, delimiter: str = '_') -> str:
    """Convert an underscore separated string to camel case with first word not capitalized.
        hello_world -> helloWorld
    """
    components = s.split(delimiter)
    return f"{components[0]}{''.join(x.title() for x in components[1:])}"


def capitalize(word: str):
    return word[:1].upper() + word[1:]


def capitalize_for_outputs(outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Capitalize for XSOAR outputs"""
    capitalized_outputs: List[Dict[str, Any]] = []
    for output in outputs:
        capitalized_output: Dict[str, Any] = {}
        for field, value in output.items():
            if isinstance(value, str) or isinstance(value, bool):
                capitalized_output[capitalize(field)] = value
            elif isinstance(value, dict):
                capitalized_output[capitalize(field)] = {}
                for sub_field, sub_value in value.items():
                    if isinstance(sub_value, str) or isinstance(value, bool):
                        capitalized_output[capitalize(field)][capitalize(sub_field)] = sub_value
                    elif isinstance(sub_value, dict):
                        capitalized_output[capitalize(field)][capitalize(sub_field)] = {}
                        for sub_sub_field, sub_sub_value in sub_value.items():
                            capitalized_output[capitalize(field)][capitalize(sub_field)]\
                                [capitalize(sub_sub_field)] = sub_sub_value  # Support up to dict[x: dict[y: dict]]
        capitalized_outputs.append(capitalized_output)

    return capitalized_outputs


def command_with_all_fields_readable_list(results: List[Dict[str, Any]], result_name: str, output_prefix: str,
                                          outputs_key_field: str = 'id') -> CommandResults:
    """Get entry types list from TOPdesk."""

    if len(results) == 0:
        return CommandResults(readable_output=f'No {result_name} found')

    readable_output = tableToMarkdown(f'{INTEGRATION_NAME} {result_name}', capitalize_for_outputs(results),
                                      removeNull=True)

    return CommandResults(
        readable_output=readable_output,
        outputs_prefix=f'{INTEGRATION_NAME}.{output_prefix}',
        outputs_key_field=outputs_key_field,
        outputs=capitalize_for_outputs(results),
        raw_response=results
    )


def get_incidents_with_pagination(client: Client, max_fetch: int, query: str, modification_date_start: str,
                                  modification_date_end: str) -> List[Dict[str, Any]]:
    incidents = []
    max_incidents = int(max_fetch)
    number_of_requests = math.ceil(max_incidents / MAX_API_PAGE_SIZE)
    if max_incidents < MAX_API_PAGE_SIZE:
        page_size = max_incidents
    else:
        page_size = MAX_API_PAGE_SIZE

    start = 0
    for index in range(number_of_requests):
        incidents += client.get_list_with_query(list_type="incidents",
                                                start=start,
                                                page_size=page_size,
                                                query=query,
                                                modification_date_start=modification_date_start,
                                                modification_date_end=modification_date_end)
        start += page_size
    return incidents


def get_incidents_list(client: Client, modification_date_start: str = None, modification_date_end: str = None,
                       args: Dict[str, Any] = {}) -> List[Dict[str, Any]]:
    """Get list of incidents from TOPdesk."""
    if args.get('incident_id', None):
        incidents = [client.get_single_endpoint(f"/incidents/id/{args.get('incident_id')}")]
    elif args.get('incident_number', None):
        incidents = [client.get_single_endpoint(f"/incidents/number/{args.get('incident_number')}")]
    else:
        allowed_statuses = [None, 'firstLine', 'secondLine', 'partial']
        if args.get('status', None) not in allowed_statuses:
            raise (ValueError(f"status {args.get('status', None)} id not in "
                              f"the allowed statuses list: {allowed_statuses}"))
        else:
            filter_arguments: Dict[str, Any] = {"status": "status",
                                                "caller_id": "caller",
                                                "branch_id": "branch",
                                                "category": "category",
                                                "subcategory": "subcategory",
                                                "call_type": "callType",
                                                "entry_type": "entryType"}
            old_query_not_allowed_filters = ["category", "subcategory", "call_type", "entry_type"]

            query = args.get('query', None)
            for filter_arg in filter_arguments.keys():
                if not client.new_query:
                    if args.get(filter_arg, None) and filter_arg in old_query_not_allowed_filters:
                        raise KeyError(f"{filter_arg} is not supported with old query setting.")

                query = client.add_filter_to_query(query=query,
                                                   filter_name=filter_arguments.get(filter_arg, None),
                                                   filter_arg=args.get(filter_arg, None))
            incidents = client.get_list_with_query(list_type="incidents",
                                                   start=args.get('start', None),
                                                   page_size=args.get('page_size', None),
                                                   query=query,
                                                   modification_date_start=modification_date_start,
                                                   modification_date_end=modification_date_end)

    return incidents


def incidents_to_command_results(incidents: List[Dict[str, Any]]) -> CommandResults:
    """Receive incidents from api and convert to CommandResults"""
    if len(incidents) == 0:
        return CommandResults(readable_output='No incidents found')

    headers = ['id', 'number', 'request', 'line', 'actions', 'caller name', 'status', 'operator', 'priority']

    readable_incidents = []
    for incident in incidents:
        readable_incident = {
            'Id': incident.get('id', None),
            'Number': incident.get('number', None),
            'Request': incident.get('request', None),
            'Line': incident.get('status', None),
            'CallerName': incident.get('caller').get('dynamicName', None) if incident.get('caller') else None,
            'Status': incident.get('processingStatus').get('name', None) if incident.get('processingStatus') else None,
            'Operator': incident.get('operator').get('name', None) if incident.get('operator') else None,
            'Priority': incident.get('priority', None)
        }

        readable_incidents.append(readable_incident)

    readable_output = tableToMarkdown(f'{INTEGRATION_NAME} incidents', readable_incidents,
                                      headers=headers,
                                      removeNull=True)

    return CommandResults(
        readable_output=readable_output,
        outputs_prefix=f'{INTEGRATION_NAME}.Incident',
        outputs_key_field='Id',
        outputs=capitalize_for_outputs(incidents),
        raw_response=incidents
    )


def incident_func_command(args: Dict[str, Any], client_func: Callable, action: str) -> CommandResults:
    """Abstract class for executing client_func and returning TOPdesk incident as a result."""
    response = client_func(args)

    if not response.get('id', None):
        raise Exception(f"Recieved Error when {action} incident in TOPdesk:\n{response}")

    return incidents_to_command_results([response])


''' COMMAND FUNCTIONS '''
''' List Commands '''


def list_persons_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    """Get persons list from TOPdesk"""

    persons = client.get_list_with_query(list_type="persons",
                                         start=args.get('start', None),
                                         page_size=args.get('page_size', None),
                                         query=args.get('query', None))
    if len(persons) == 0:
        return CommandResults(readable_output='No persons found')

    headers = ['Id', 'Name', 'Telephone', 'JobTitle', 'Department', 'City',
               'BranchName', 'Room']

    readable_persons = []
    for person in persons:
        readable_person = {
            'Id': person.get('id', None),
            'Name': person.get('dynamicName', None),
            'Telephone': person.get('phoneNumber', None),
            'JobTitle': person.get('jobTitle', None),
            'Department': person.get('department', None),
            'City': person.get('city', None),
            'BranchName': person.get('branch', {}).get('name', None) if person.get('branch') else None,
            'Room': None
        }
        if person.get('location', None):
            readable_person['Room'] = person.get('location', None).get('room', None)

        readable_persons.append(readable_person)

    readable_output = tableToMarkdown(f'{INTEGRATION_NAME} persons',
                                      readable_persons,
                                      headers=headers,
                                      removeNull=True)

    return CommandResults(
        readable_output=readable_output,
        outputs_prefix=f'{INTEGRATION_NAME}.Person',
        outputs_key_field='Id',
        outputs=capitalize_for_outputs(persons),
        raw_response=persons
    )


def list_operators_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    """Get operators list from TOPdesk"""

    operators = client.get_list_with_query(list_type="operators",
                                           start=args.get('start', None),
                                           page_size=args.get('page_size', None),
                                           query=args.get('query', None))
    if len(operators) == 0:
        return CommandResults(readable_output='No operators found')

    headers = ['Id', 'Name', 'Telephone', 'JobTitle', 'Department',
               'City', 'BranchName', 'LoginName']

    readable_operators = []
    for operator in operators:
        readable_operators.append({
            'Id': operator.get('id', None),
            'Name': operator.get('dynamicName', None),
            'Telephone': operator.get('phoneNumber', None),
            'JobTitle': operator.get('jobTitle', None),
            'Department': operator.get('department', None),
            'City': operator.get('city', None),
            'BranchName': operator.get('branch', {}).get('name', None) if operator.get('branch') else None,
            'LoginName': operator.get('tasLoginName', None),
        })

    readable_output = tableToMarkdown(f'{INTEGRATION_NAME} operators',
                                      readable_operators,
                                      headers=headers,
                                      removeNull=True)

    return CommandResults(
        readable_output=readable_output,
        outputs_prefix=f'{INTEGRATION_NAME}.Operator',
        outputs_key_field='Id',
        outputs=capitalize_for_outputs(operators),
        raw_response=operators
    )


def entry_types_command(client: Client) -> CommandResults:
    """Get entry types list from TOPdesk"""
    entry_types = client.get_list('/incidents/entry_types')
    return command_with_all_fields_readable_list(results=entry_types,
                                                 result_name='entry types',
                                                 output_prefix='EntryType',
                                                 outputs_key_field='Id')


def call_types_command(client: Client) -> CommandResults:
    """Get call types list from TOPdesk"""
    call_types = client.get_list("/incidents/call_types")
    return command_with_all_fields_readable_list(results=call_types,
                                                 result_name='call types',
                                                 output_prefix='CallType',
                                                 outputs_key_field='Id')


def categories_command(client: Client) -> CommandResults:
    """Get categories list from TOPdesk"""
    categories = client.get_list("/incidents/categories")
    return command_with_all_fields_readable_list(results=categories,
                                                 result_name='categories',
                                                 output_prefix='Category',
                                                 outputs_key_field='Id')


def escalation_reasons_command(client: Client) -> CommandResults:
    """Get escalation reasons list from TOPdesk"""
    escalation_reasons = client.get_list("/incidents/escalation-reasons")
    return command_with_all_fields_readable_list(results=escalation_reasons,
                                                 result_name='escalation reasons',
                                                 output_prefix='EscalationReason',
                                                 outputs_key_field='Id')


def deescalation_reasons_command(client: Client) -> CommandResults:
    """Get deescalation reasons list from TOPdesk"""
    deescalation_reasons = client.get_list("/incidents/deescalation-reasons")
    return command_with_all_fields_readable_list(results=deescalation_reasons,
                                                 result_name='deescalation reasons',
                                                 output_prefix='DeescalationReason',
                                                 outputs_key_field='Id')


def archiving_reasons_command(client: Client) -> CommandResults:
    """Get archiving reasons list from TOPdesk"""
    archiving_reasons = client.get_list("/archiving-reasons")
    return command_with_all_fields_readable_list(results=archiving_reasons,
                                                 result_name='archiving reasons',
                                                 output_prefix='ArchiveReason',
                                                 outputs_key_field='Id')


def subcategories_command(client: Client) -> CommandResults:
    """Get categories list from TOPdesk"""
    subcategories = client.get_list("/incidents/subcategories")

    if len(subcategories) == 0:
        return CommandResults(readable_output='No subcategories found')

    subcategories_with_categories = []
    for subcategory in subcategories:
        subcategory_with_category = {"Id": subcategory.get("id", None),
                                     "Name": subcategory.get("name", None),
                                     "CategoryId": None,
                                     "CategoryName": None}
        if subcategory.get("category", None):
            subcategory_with_category["CategoryId"] = subcategory.get("category", None).get("id", None)
            subcategory_with_category["CategoryName"] = subcategory.get("category", None).get("name", None)

        subcategories_with_categories.append(subcategory_with_category)

    headers = ['Id', 'Name', 'CategoryId', 'CategoryName']
    readable_output = tableToMarkdown(f'{INTEGRATION_NAME} subcategories',
                                      subcategories_with_categories,
                                      headers=headers,
                                      removeNull=True)

    return CommandResults(
        readable_output=readable_output,
        outputs_prefix=f'{INTEGRATION_NAME}.Subcategories',
        outputs_key_field='Id',
        outputs=capitalize_for_outputs(subcategories),
        raw_response=subcategories
    )


def branches_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    """Get branches list from TOPdesk"""

    branches = client.get_list_with_query(list_type="branches",
                                          start=args.get('start', None),
                                          page_size=args.get('page_size', None),
                                          query=args.get('query', None))
    if len(branches) == 0:
        return CommandResults(readable_output='No branches found')

    headers = ['Id', 'Status', 'Name', 'Phone', 'Website', 'Address']

    readable_branches = []
    for branch in branches:
        readable_branch = {
            'Id': branch.get('id', None),
            'Status': branch.get('status', None),
            'Name': branch.get('name', None),
            'Phone': branch.get('phone', None),
            'Website': branch.get('website', None),
            'Address': branch.get('address', {}).get('addressMemo', None)
        }
        readable_branches.append(readable_branch)

    readable_output = tableToMarkdown(f'{INTEGRATION_NAME} branches',
                                      readable_branches,
                                      headers=headers,
                                      removeNull=True)

    return CommandResults(
        readable_output=readable_output,
        outputs_prefix=f'{INTEGRATION_NAME}.Branch',
        outputs_key_field='Id',
        outputs=capitalize_for_outputs(branches),
        raw_response=branches
    )


def get_incidents_list_command(client: Client, args: Dict[str, Any]) -> Union[CommandResults, str]:
    """Parse arguments and return incidents list as CommandResults."""
    try:
        command_results = incidents_to_command_results(get_incidents_list(client=client, args=args))
        return command_results
    except Exception as e:
        if 'Error parsing query' in str(e):
            return 'Error parsing query: make sure you are using the right query type.'
        else:
            raise e


def incident_touch_command(args: Dict[str, Any], client_func: Callable, action: str) -> CommandResults:
    """Try setting caller as a reqistered caller.
    If caller is not registered, set the caller argument as caller name.
    A registered caller is one that has a TOPdesk account that can e linked to the call.
    This function implements incident_create and incident_update commands.
    """
    try:
        args['registered_caller'] = True
        return incident_func_command(args=args,
                                     client_func=client_func,
                                     action=action)
    except Exception as e:
        if "'callerLookup.id' cannot be parsed" in str(e):
            args['registered_caller'] = False
            return incident_func_command(args=args,
                                         client_func=client_func,
                                         action=action)
        else:
            raise e


def incident_do_command(client: Client, args: Dict[str, Any], action: str) -> CommandResults:
    """Preform an action on an incident and return it as CommandResults."""
    return incidents_to_command_results([client.incident_do(action=action,
                                                            incident_id=args.get("id", None),
                                                            incident_number=args.get("number", None),
                                                            reason_id=args.get(f"{action}_reason_id", None))])


def attachment_upload_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    """Upload attachment to certain incident in TOPdesk"""
    file_entry = args.get('file')
    file_name = demisto.dt(demisto.context(), "File(val.EntryID=='" + file_entry + "').Name")
    if not file_name:  # in case of info file
        file_name = demisto.dt(demisto.context(), "InfoFile(val.EntryID=='" + file_entry + "').Name")

    if not file_name:
        raise ValueError(f"Could not fine file in entry with entry_id: {file_entry}")

    if isinstance(file_name, list):  # If few files
        if args.get('file_name', None) and args.get('file_name') in file_name:
            file_name = args.get('file_name')
        else:
            file_name = file_name[0]

    invisible_for_caller = bool(args.get('invisible_for_caller', False))

    response = client.attachment_upload(incident_id=args.get('id', None),
                                        incident_number=args.get('number', None),
                                        file_entry=file_entry,
                                        file_name=file_name,
                                        invisible_for_caller=invisible_for_caller,
                                        file_description=args.get('file_description', None))

    if not response.get("downloadUrl", None):
        raise Exception(f"Failed uploading file: {response}")

    headers = ['Id', 'FileName', 'DownloadUrl', 'Size', 'Description',
               'InvisibleForCaller', 'EntryDate', 'Operator']
    half_camelized_headers = [half_camelize(header, ' ') for header in headers]
    readable_attachment: List[Dict[str, Any]] = [{}]
    for header, half_camelized_header in zip(headers, half_camelized_headers):
        readable_attachment[0][header] = response.get(half_camelized_header, None)

    readable_output = tableToMarkdown(f"{INTEGRATION_NAME} attachment of incident {args.get('number', None)}",
                                      readable_attachment,
                                      headers=headers,
                                      removeNull=True)

    return CommandResults(
        readable_output=readable_output,
        outputs_prefix=f'{INTEGRATION_NAME}.Attachment',
        outputs_key_field='Id',
        outputs=capitalize_for_outputs([response]),
        raw_response=response
    )


''' FETCH & MIRRORING COMMANDS'''


def fetch_incidents(client: Client,
                    last_run: Dict[str, Any],
                    demisto_params: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Fetches incidents from TOPdesk."""

    first_fetch_datetime = dateparser.parse(demisto_params.get('first_fetch', '3 days'))
    last_fetch_datetime = last_run.get('last_fetch', None)

    if not last_fetch_datetime:
        if first_fetch_datetime:
            last_fetch_datetime = first_fetch_datetime
        else:
            raise Exception("Could not find last fetch time.")

    latest_created_time = last_fetch_datetime
    incidents: List[Dict[str, Any]] = []

    topdesk_incidents = get_incidents_with_pagination(client=client,
                                                      max_fetch=int(demisto_params.get('max_fetch', 10)),
                                                      query=demisto_params.get('query', None),
                                                      modification_date_start=demisto_params.get(
                                                          'modification_date_start', None),
                                                      modification_date_end=demisto_params.get(
                                                          'modification_date_end', None))

    for topdesk_incident in topdesk_incidents:
        if topdesk_incident.get('creationDate', None):
            creation_datetime = dateparser.parse(topdesk_incident['creationDate'])
            incident_created_time = creation_datetime
        else:
            incident_created_time = last_fetch_datetime
        if int(last_fetch_datetime.timestamp()) < int(incident_created_time.timestamp()):
            labels: List[Dict[str, Any]] = []
            for topdesk_incident_field, topdesk_incident_value in topdesk_incident.items():
                if isinstance(topdesk_incident_value, str):
                    labels.append({
                        'type': topdesk_incident_field,
                        'value': topdesk_incident_value
                    })
                else:
                    labels.append({
                        'type': topdesk_incident_field,
                        'value': json.dumps(topdesk_incident_value)
                    })

            incidents.append({
                'name': f"TOPdesk incident {topdesk_incident['number']}",
                'details': json.dumps(topdesk_incident),
                'occurred': incident_created_time.strftime(DATE_FORMAT),
                'rawJSON': json.dumps(topdesk_incident),
                'labels': labels
            })
        if latest_created_time.timestamp() < incident_created_time.timestamp():
            latest_created_time = incident_created_time

    return {'last_fetch': latest_created_time}, incidents


def test_module(client: Client, demisto_last_run: Dict[str, Any], demisto_params: Dict[str, Any]) -> str:
    """Test API connectivity and authentication."""
    try:
        if demisto_params.get('isFetch'):
            fetch_incidents(client=client,
                            last_run=demisto_last_run,
                            demisto_params=demisto_params)
        else:
            client.get_list("/incidents/call_types")
    except DemistoException as e:
        if 'Error 401' in str(e):
            return 'Authorization Error: make sure username and password are correctly set'
        if '[404] - Not Found' in str(e):
            return 'Page Not Found: make sure the url is correctly set'
        else:
            raise e
    return 'ok'


''' MAIN FUNCTION '''


def main() -> None:
    """main function, parses params and runs command functions."""

    # get the service API url
    demisto_params = demisto.params()
    base_url = urljoin(demisto_params['url'], '/api')
    verify_certificate = not demisto_params.get('insecure', False)

    demisto.debug(f'Command being called is {demisto.command()}')
    try:
        encoded_credentials = basicauth.encode(username=demisto.params().get('username'),
                                               password=demisto.params().get('password'))

        headers = {
            'Authorization': encoded_credentials
        }
        client = Client(
            base_url=base_url,
            verify=verify_certificate,
            headers=headers,
            new_query=demisto_params['new_query'])

        if demisto.command() == 'test-module':
            result = test_module(client, demisto.getLastRun(), demisto_params)
            return_results(result)

        elif demisto.command() == 'topdesk-persons-list':
            return_results(list_persons_command(client, demisto.args()))
        elif demisto.command() == 'topdesk-operators-list':
            return_results(list_operators_command(client, demisto.args()))
        elif demisto.command() == 'topdesk-entry-types-list':
            return_results(entry_types_command(client))
        elif demisto.command() == 'topdesk-call-types-list':
            return_results(call_types_command(client))
        elif demisto.command() == 'topdesk-categories-list':
            return_results(categories_command(client))
        elif demisto.command() == 'topdesk-escalation-reasons-list':
            return_results(escalation_reasons_command(client))
        elif demisto.command() == 'topdesk-deescalation-reasons-list':
            return_results(deescalation_reasons_command(client))
        elif demisto.command() == 'topdesk-archiving-reasons-list':
            return_results(archiving_reasons_command(client))
        elif demisto.command() == 'topdesk-subcategories-list':
            return_results(subcategories_command(client))
        elif demisto.command() == 'topdesk-branches-list':
            return_results(branches_command(client, demisto.args()))
        elif demisto.command() == 'topdesk-incidents-list':
            return_results(get_incidents_list_command(client, demisto.args()))

        elif demisto.command() == 'topdesk-incident-create':
            return_results(incident_touch_command(args=demisto.args(),
                                                  client_func=client.create_incident,
                                                  action="creating"))
        elif demisto.command() == 'topdesk-incident-update':
            return_results(incident_touch_command(args=demisto.args(),
                                                  client_func=client.update_incident,
                                                  action="updating"))

        elif demisto.command() == 'topdesk-incident-escalate':
            return_results(incident_do_command(client, demisto.args(), "escalate"))
        elif demisto.command() == 'topdesk-incident-deescalate':
            return_results(incident_do_command(client, demisto.args(), "deescalate"))
        elif demisto.command() == 'topdesk-incident-archive':
            return_results(incident_do_command(client, demisto.args(), "archive"))
        elif demisto.command() == 'topdesk-incident-unarchive':
            return_results(incident_do_command(client, demisto.args(), "unarchive"))

        elif demisto.command() == 'topdesk-incident-attachment-upload':
            return_results(attachment_upload_command(client, demisto.args()))

        elif demisto.command() == 'fetch-incidents':
            last_fetch, incidents = fetch_incidents(client=client,
                                                    last_run=demisto.getLastRun(),
                                                    demisto_params=demisto_params)
            demisto.setLastRun(last_fetch)
            demisto.incidents(incidents)
        else:
            raise NotImplementedError(f"command {demisto.command()} does not exist in {INTEGRATION_NAME} integration")

    # Log exceptions and return errors
    except Exception as e:
        demisto.error(traceback.format_exc())  # print the traceback
        return_error(f'Failed to execute {demisto.command()} command.\nError:\n{str(e)}')


''' ENTRY POINT '''

if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
