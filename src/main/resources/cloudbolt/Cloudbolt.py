#
# Copyright 2017 XEBIALABS
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

import json, time, re, sys, os, zipfile
from xlrelease.HttpRequest import HttpRequest
from xlrelease.CredentialsFallback import CredentialsFallback
from org.apache.http.client import ClientProtocolException


class CloudboltClient(object):
    def __init__(self, server, username, password):
        creds = CredentialsFallback(server, username, password).getCredentials()
        self.http_request = HttpRequest(server, creds['username'], creds['password'])

    @staticmethod
    def get_client(server, username, password):
        return CloudboltClient(server, username, password)

    def parse_output(self, lines):
        result_output = ""
        for line in lines:
            result_output = '\n'.join([result_output, line])
        return result_output

    def api_call(self, method, endpoint, **options):

        try:
            options['method'] = method.upper()
            options['context'] = endpoint
            response = self.http_request.doRequest(**options)
        except ClientProtocolException:
            raise Exception("URL is not valid")
        if not response.isSuccessful():
            raise Exception("HTTP response code %s (%s)" % (response.getStatus(), response.errorDump()))
        return response

#
# Task Methods /API Calls
#
#

    def cloudbolt_provisionserver(self,variables):
        order_id = self.create_order_for_group(variables['groupId'], variables['ownerId'])

        order_item = self.prov_order_item_dict(
            variables['envId'],
            variables['hostname'],
            variables['osBuildId'],
            variables['parameters'],
            variables['preconfigurations'],
            variables['appIds'])

        self.add_prov_order_item(order_id, order_item)

        order = self.submit_order(order_id)
        if order.get('status', '') == 'PENDING':
            # If it's awaiting approval, that must mean it was not auto-approved and, if there was an
            #  order approval hook, it did not approve it. Attempt to approve now.
            order = self.approve_order(order_id)

        # Here we expect the order to be approved; if not,
        # something in this group or environment is misconfigured and manual
        # intervention is required.
        if order.get('status', '') != 'ACTIVE':
            sys.exit("Failure: The submitted order is not active. Please ensure "
                     "that the user has approval permission on this group or that "
                     "auto-approval is enabled for this group or environment.")

        order = self.wait_for_order_completion(order_id, int(variables['waitTimeout']), int(variables['waitInterval']))

        if order['status'] != 'SUCCESS':
            raise Exception("Order not successful. Please retry")

        endpoint = order["_links"]["jobs"][0]["href"]
        resp = self.api_call('GET', endpoint, contentType="application/json")
        job = json.loads(resp.getResponse())
        match = re.search("\(ID[ ]*([\d]+)\)", job["output"].replace("\n", ""))
        serverId = match.group(1)
        return {"serverId" : serverId}

    def cloudbolt_decommissionserver(self, variables):
        order_id = self.create_order_for_group(variables['groupId'])
        order_item = self.decom_order_item_dict(variables['envId'], [variables['serverId']])
        self.add_decom_order_item(order_id, order_item)
        order = self.submit_order(order_id)
        if order.get('status', '') == 'PENDING':
            order = self.approve_order(order_id)
        # Here we expect the order to be approved; if not,
        # something in this group or environment is misconfigured and manual
        # intervention is required.
        if order['status'] != 'ACTIVE':
            sys.exit("Failure: The submitted order is not active. Please ensure "
                     "that the user has approval permission on this group or that "
                     "auto-approval is enabled for this group or environment.")

        order = self.wait_for_order_completion(order_id, int(variables['waitTimeout']), int(variables['waitInterval']))

        if order['status'] != 'SUCCESS':
            raise Exception("Order not successful. Please retry")
        return {}


#
# Helper Methods
#
#

    def create_order_for_group(self, group_id, owner_id=None):
        """
        Starts a new order for this group on the  connection.
        Optionally sets the owner to the User with ID=owner_id.
        """
        print 'Creating order for group {0}...'.format(group_id)
        body = {'group': "/api/v2/groups/{0}".format(group_id)}
        endpoint = '/api/v2/orders/'
        if owner_id:
            body['owner'] = '/api/v2/users/{0}'.format(owner_id)
            print '... and owner {0}'.format(owner_id)
        resp = self.api_call('POST', endpoint, body=json.dumps(body), contentType="application/json")
        response = json.loads(resp.getResponse())
        if 'status_code' in response and response['status_code'] not in range(200, 300):
            error = self.pretty_print(response)
            print "Error creating order through the API: {0}".format(error)
            sys.exit(1)

        order_url = response['_links']['self']['href']
        order_id = order_url.replace('/api/v2/orders/', '')

        print 'Order {order_id} created.'.format(order_id=order_id)
        return int(order_id)

    def pretty_print(self,dictionary):
        """
        Method to print out the entire response dict in a nice way
        """
        pp = ""
        for key in dictionary.keys():
            pp += "{0}: {1}\n".format(key, dictionary[key])
        return pp

    def get_order(self, order_id):
        """
        Return dict representing an order details JSON.
        """
        endpoint = "/api/v2/orders/{0}/".format(order_id)
        resp = self.api_call('GET', endpoint, contentType="application/json")
        response = json.loads(resp.getResponse())

        return response

    def submit_order(self, order_id):
        """
        Submit order for approval.
        """
        print 'Submitting order {0}...'.format(order_id)
        endpoint = "/api/v2/orders/{0}/actions/submit/".format(order_id)
        resp = self.api_call('POST', endpoint,body="", contentType="application/json")
        response = json.loads(resp.getResponse())
        print 'Response:\n', response
        return response

    def approve_order(self, order_id):
        """
        Approve order.
        """
        print 'Approving order {0}...'.format(order_id)
        endpoint = "/api/v2/orders/{0}/actions/approve/".format(order_id)
        response = self.api_call('POST', endpoint, contentType="application/json")
        print 'Response:\n', response
        return response

    def wait_for_order_completion(self, order_id, timeout_sec, interval_sec):
        """
        Polls for this order's status to change from 'ACTIVE', retrying every
        interval_sec seconds.

        When complete, prints the output & error fields from each job in the order.

        If the order suceeds, return 0.  If the order fails, return 1, if the wait
        timeout is reached, return 3.
        """
        print 'Waiting for order to complete (timeout {0}s)...'.format(timeout_sec)
        order = self.get_order(order_id)

        start = time.time()
        waited = 0
        completed = ['SUCCESS', 'WARNING', 'FAILURE']
        while waited < timeout_sec and order['status'] not in completed:
            time.sleep(interval_sec)
            waited = time.time() - start
            order = self.get_order(order_id)
            sys.stdout.write('.')
            sys.stdout.flush()

        print "\n"
        if waited >= timeout_sec:
            # By returning this instead of printing, the caller can send it
            # to stderr instead (via sys.exit() for example).
            print ("Failed: Order did not complete within {0}s. "
                   "Most recent order status was {1}."
                   .format(timeout_sec, order['status']))
            raise Exception("Failed: Order did not complete within {0}s. "
                            "Most recent order status was {1}."
                            .format(timeout_sec, order['status']))

        self.print_order_job_outputs(order)
        # if order['status'] != 'SUCCESS':
        #   return 1
        # return 0
        return order

    def wait_for_job_completion(self, job_id, timeout_sec, interval_sec):
        """
        Polls for this job's status to change to a completed one, retrying every
        interval_sec seconds.

        When complete, prints the output & error fields from the job.

        If the job suceeds, return 0.  If the job fails, return 1, if the wait
        timeout is reached, return 3.
        """
        print 'Waiting for job to complete (timeout {0}s)...'.format(timeout_sec)
        endpoint = "/api/v2/jobs/{}/".format(job_id)
        resp = self.api_call('GET', endpoint, contentType="application/json")
        job = json.loads(resp.getResponse())

        start = time.time()
        waited = 0
        completed = ['SUCCESS', 'WARNING', 'FAILURE']
        while waited < timeout_sec and job['status'] not in completed:
            time.sleep(interval_sec)
            waited = time.time() - start
            endpoint = "/api/v2/jobs/{}/".format(job_id)
            resp = self.api_call('GET', endpoint, contentType="application/json")
            job = json.loads(resp.getResponse())
            sys.stdout.write('.')
            sys.stdout.flush()

        print "\n"
        if waited >= timeout_sec:
            # By returning this instead of printing, the caller can send it
            # to stderr instead (via sys.exit() for example).
            print ("Failed: Job did not complete within {0}s. "
                   "Most recent job status was {1}."
                   .format(timeout_sec, job['status']))
            return 3

        print job["_links"]["self"]["title"]
        print "Output: ", job.get("output", "no output")
        print "Errors: ", job.get("errors", "no errors")
        if job['status'] != 'SUCCESS':
            return 1
        return 0

    def print_order_job_outputs(self, order):
        """
        Prints the output & error for each job within this order
        """
        for j in order["_links"]["jobs"]:
            endpoint = j["href"]
            resp = self.api_call('GET', endpoint, contentType="application/json")
            job = json.loads(resp.getResponse())
            print job["_links"]["self"]["title"]
            print "Output: ", job.get("output", "no output")
            print "Errors: ", job.get("errors", "no errors")

    def zipdir(self, dir_path=None, zip_path=None, include_dir_in_zip=True):
        """
        Zips up `dir_path` and returns the zip file's path.

        `dir_path` may be '~/a/b/dirname' or '/c/d/dirname' or 'e/f/dirname'.

        `zip_path`: optional path for the new zip file.  By default the zip file is
        created next to the directory and named after it.

        `include_dir_in_zip`: if True (default), the archive will have one base
        directory named after the directory being zipped; otherwise no prefix will
        be added to the archive members.

        E.g.
            zip_dir('~/a/b/dirname')
              -> dirname.zip with files like 'dirname/blueprint.json'
        """
        dir_path = dir_path.rstrip('/')
        dir_path = os.path.abspath(os.path.expanduser(dir_path))

        if not zip_path:
            zip_path = dir_path + ".zip"
        if not os.path.isdir(dir_path):
            raise OSError("dir_path argument must point to a directory. "
                          "'%s' does not." % dir_path)
        parent_dir, dir_to_zip = os.path.split(dir_path)

        # Little nested function to prepare the proper archive path
        def trimPath(path):
            archive_path = path.replace(parent_dir, "", 1)
            if parent_dir:
                archive_path = archive_path.replace(os.path.sep, "", 1)
            if not include_dir_in_zip:
                archive_path = archive_path.replace(dir_to_zip + os.path.sep, "", 1)
            return os.path.normcase(archive_path)

        out_file = zipfile.ZipFile(
            zip_path, "w", compression=zipfile.ZIP_DEFLATED)
        for (archive_path, dir_names, file_names) in os.walk(dir_path):
            for fileName in file_names:
                filePath = os.path.join(archive_path, fileName)
                out_file.write(filePath, trimPath(filePath))
        out_file.close()
        return zip_path

    def prov_order_item_dict(self,
            env_id,
            hostname=None,
            os_build_id=None,
            parameters={},
            preconfigurations={},
            app_ids=[]):
        """
        Helper function to build a dict representing a server provisioning order item.
        """
        order_item = {
            "environment": "/api/v2/environments/{0}".format(env_id)
        }
        if hostname:
            order_item['attributes'] = {"hostname": hostname}
        if os_build_id:
            order_item['os-build'] = "/api/v2/os-builds/{0}".format(os_build_id)
        if parameters:
            order_item['parameters'] = parameters
        if preconfigurations:
            order_item['preconfigurations'] = preconfigurations
        if app_ids:
            order_item['applications'] = []
            for app_id in app_ids:
                order_item['applications'].append(
                    "/api/v2/applications/{0}".format(app_id))
        return order_item

    def add_prov_order_item(self, order_id, prov_item):
        """
        Creates a new "provision server" order item on specified order.
        Args:
            order_id
            prov_item: dict representing server provisioning order item
                See API docs for samples.
        """
        print 'Adding order item to order {0}...'.format(order_id)
        print json.dumps(prov_item, indent=4)
        endpoint = "/api/v2/orders/{0}/prov-items/".format(order_id)
        response = self.api_call('POST', endpoint, body=json.dumps(prov_item), contentType="application/json")
        print 'Response:\n', response
        return response

    def decom_order_item_dict(self, env_id, server_ids):
        """
        Helper function to build a dict representing a server decom order item.
        """
        order_item = {
            "environment": "/api/v2/environments/{env_id}".format(env_id=env_id),
            "servers": []
        }

        for server_id in server_ids:
            order_item['servers'].append(
                "/api/v2/servers/{server_id}".format(server_id=server_id))
        return order_item


    def add_decom_order_item(self, order_id, decom_item):
        """
        Creates a new "decommission server" order item on specified order.
        Args:
            order_id
            decom_item: dict representing server decommissioning order item
                See API docs for samples.
        """
        print 'Adding order item to order {order_id}...'.format(order_id=order_id)
        print json.dumps(decom_item, indent=4)
        endpoint = "/api/v2/orders/{order_id}/decom-items/".format(order_id=order_id)
        response = self.api_call('POST', endpoint, body=json.dumps(decom_item), contentType="application/json")
        print 'Response:\n', response
        return response
