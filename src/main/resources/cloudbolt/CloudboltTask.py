#
# THIS CODE AND INFORMATION ARE PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EITHER EXPRESSED OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE IMPLIED WARRANTIES OF MERCHANTABILITY AND/OR FITNESS
# FOR A PARTICULAR PURPOSE. THIS CODE AND INFORMATION ARE NOT SUPPORTED BY XEBIALABS.
#

from cloudbolt.Cloudbolt import CloudboltClient

cloudbolt = CloudboltClient.get_client(server, username, password)
method = str(task.getTaskType()).lower().replace('.', '_')
call = getattr(cloudbolt, method)
response = call(locals())
for key,value in response.items():
    locals()[key] = value
