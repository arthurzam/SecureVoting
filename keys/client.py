import socket
import ssl

context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.load_verify_locations('avote_ca.pem')
context.check_hostname = False

with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
    with context.wrap_socket(sock) as ssock:
        ssock.connect(('127.0.0.1', 8443))
        ssock.write(b'Hello')
        print(ssock.version())
