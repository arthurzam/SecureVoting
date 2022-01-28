import socket
import ssl

context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_verify_locations('avote_ca.pem')
context.load_cert_chain('avote1.pem', 'avote1.key')

with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
    sock.bind(('127.0.0.1', 8443))
    sock.listen(5)
    with context.wrap_socket(sock, server_side=True) as ssock:
        conn, addr = ssock.accept()
        data = conn.recv()
        print(data)
        conn.shutdown()
        conn.close()
