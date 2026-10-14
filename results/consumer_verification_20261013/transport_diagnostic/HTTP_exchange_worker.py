
import hashlib, http.client, json, sys
from pathlib import Path
from urllib.parse import urlsplit
endpoint, directory, stem, timeout, maximum = sys.argv[1:]
output = Path(directory)
url = urlsplit(endpoint)
base = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
class CapturingConnection(base):
    def send(self, data):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError('Expected concrete HTTP bytes')
        with (output / (stem + '_HTTP_request_plaintext.raw')).open('ab') as capture:
            capture.write(data)
        return super().send(data)
connection = CapturingConnection(url.hostname, port=url.port, timeout=float(timeout))
try:
    body = sys.stdin.buffer.read()
    connection.request('POST', url.path, body=body,
                       headers={'Content-Type': 'application/json', 'Authorization': 'Bearer EMPTY'})
    response = connection.getresponse()
    raw = response.read(int(maximum) + 1)
    (output / (stem + '_response.raw')).write_bytes(raw)
    metadata = dict(status=response.status, reason=response.reason, headers=response.getheaders(),
                    body_artifact=stem + '_response.raw', body_sha256=hashlib.sha256(raw).hexdigest())
    (output / (stem + '_HTTP_response.json')).write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata))
finally:
    connection.close()
