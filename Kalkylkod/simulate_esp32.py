"""Synthetic test signal; no hardware. Stop with Ctrl+C."""
import math
import socket
import time


def sample_mv(j):
    t=j/2000
    amp=1 if t<3 else (100 if t<7 else min(200,100+(t-7)*20))
    return 1650+amp*math.sin(2*math.pi*100*t)


def serve():
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('127.0.0.1', 5000))
        server.listen(1)
        print('SIMULATED DATA: 127.0.0.1:5000, bias=1.65 V, gain=100')
        while True:
            client, _ = server.accept()
            with client:
                try:
                    client.sendall(b'#SIMULATED fs=2000 unit=pin_mV\n')
                    start = time.monotonic()
                    i = 0
                    while True:
                        data = ''.join(f'{j*500} {sample_mv(j):.6f}\n'
                                       for j in range(i, i+20)).encode('ascii')
                        client.sendall(data)
                        i += 20
                        time.sleep(max(0, start + i/2000 - time.monotonic()))
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

if __name__ == '__main__':
    try:
        serve()
    except KeyboardInterrupt:
        print('\nStopped.')
