#Grott Growatt monitor :  Proxy 
#       
# Updated: 2022-08-07
# Version 2.7.5

import socket
import select
import time
import sys
import struct
import textwrap
from itertools import cycle # to support "cycling" the iterator
import time, json, datetime, codecs
## to resolve errno 32: broken pipe issue (only linux)
if sys.platform != 'win32' :
   from signal import signal, SIGPIPE, SIG_DFL

from grottdata import procdata
from grottpolicy import classify_proxy_record, take_frames, validate_record

#import libscrc for additional crc checking
# for compat reason (generate a message in the log) also done in proxy _init_
try:
    import libscrc
except Exception:
    print("\t **********************************************************************************")
    print("\t - Grott - libscrc not installed, no CRC checking only record validation on length!")
    print("\t **********************************************************************************")


# Changing the buffer_size and delay, you can improve the speed and bandwidth.
# But when buffer get to high or delay go too down, you can broke things
buffer_size = 4096
#buffer_size = 65535
delay = 0.0002

class Forward:
    def __init__(self):
        self.forward = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def start(self, host, port):
        try:
            self.forward.connect((host, port))
            return self.forward
        except Exception as e:
            print("\t - Grott - grottproxy forward error : ", e) 
            #print(e)
            return False  

class Proxy:
    def __init__(self, conf):
        self.input_list = []
        self.channel = {}
        self.stream_buffers = {}
        self.running = True
        print("\nGrott proxy mode started")

        # for compatibility reasons test if libscrc is installed and send error message
        # if not installed processing wil continue but records will only be validated on length and not on crc. 
        try:     
            import libscrc
        except:
            print("\t **********************************************************************************")
            print("\t - Grott - libscrc not installed, no CRC checking only record validation on length!") 
            print("\t **********************************************************************************")

        ## to resolve errno 32: broken pipe issue (Linux only)
        if sys.platform != 'win32':
            signal(SIGPIPE, SIG_DFL) 
        ## 
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        #set default grottip address
        if conf.grottip == "default" : conf.grottip = '0.0.0.0'
        self.server.bind((conf.grottip, conf.grottport))
        #socket.gethostbyname(socket.gethostname())
        try: 
            hostname = (socket.gethostname())    
            print("Hostname :", hostname)
            print("IP : ", socket.gethostbyname(hostname), ", port : ", conf.grottport, "\n")
        except:  
            print("IP and port information not available") 

        self.server.listen(200)
        self.forward_to = (conf.growattip, conf.growattport)

    def stop(self):
        """Unblock the accept loop and close sockets it still owns."""
        self.running = False
        for sock in list(self.stream_buffers):
            self._discard_pending(sock)
        for sock in list(self.input_list):
            try:
                sock.close()
            except OSError:
                pass
        try:
            self.server.close()
        except OSError:
            pass

    def _discard_pending(self, sock):
        pending = self.stream_buffers.pop(sock, b"")
        if pending:
            print("\t - Grott discarded incomplete frame: length=%s" % len(pending))
        return pending

    def main(self, conf):
        self.input_list.append(self.server)
        while self.running:
            time.sleep(delay)
            try:
                inputready, outputready, exceptready = select.select(self.input_list, [], [], 0.5)
            except (OSError, ValueError):
                break
            if not self.running:
                break
            for self.s in inputready:
                if self.s == self.server:
                    self.on_accept(conf)
                    break
                try: 
                    self.data, self.addr = self.s.recvfrom(buffer_size)
                except: 
                    if conf.verbose : print("\t - Grott connection error") 
                    self.on_close(conf)   
                    break
                if len(self.data) == 0:
                    self.on_close(conf)
                    break
                else:
                    self.on_recv(conf)

    def on_accept(self, conf):
        clientsock, clientaddr = self.server.accept()
        # noforward is an explicit dev switch. The default remains cloud forwarding.
        self.stream_buffers[clientsock] = b""
        if getattr(conf, "noforward", False):
            if conf.verbose:
                print("\t -", clientaddr, "has connected (noforward, no upstream)")
            self.input_list.append(clientsock)
            self.channel[clientsock] = None
            return
        forward = Forward().start(self.forward_to[0], self.forward_to[1])
        if forward:
            if conf.verbose: print("\t -", clientaddr, "has connected")
            self.input_list.append(clientsock)
            self.input_list.append(forward)
            self.channel[clientsock] = forward
            self.channel[forward] = clientsock
        else:
            if conf.verbose: 
                print("\t - Can't establish connection with remote server."),
                print("\t - Closing connection with client side", clientaddr)
            self.stream_buffers.pop(clientsock, None)
            clientsock.close()

    def on_close(self, conf):
        if conf.verbose:
            # try / except to resolve errno 107: Transport endpoint is not connected
            try:
                print("\t -", self.s.getpeername(), "has disconnected")
            except Exception:
                print("\t -", "peer has disconnected")

        peer = self.channel.get(self.s)
        pending = self._discard_pending(self.s)
        if peer is not None:
            pending = pending + self._discard_pending(peer)
        if self.s in self.input_list:
            self.input_list.remove(self.s)
        if peer is None:
            try:
                self.s.close()
            except OSError:
                pass
            self.channel.pop(self.s, None)
            return

        # remove objects from input_list
        if peer in self.input_list:
            self.input_list.remove(peer)
        out = peer
        # close the connection with client
        self.channel[out].close()  # equivalent to do self.s.close()
        # close the connection with remote server
        self.channel[self.s].close()
        # delete both objects from channel dict
        del self.channel[out]
        del self.channel[self.s]

    def on_recv(self, conf):
        # Logger sockets are a byte stream. Upstream replies stay one recv
        # at a time so an existing server message is not reframed.
        if self.s in self.stream_buffers:
            self._recv_logger_stream(conf)
        else:
            self._handle_record(conf, self.data)

    def _recv_logger_stream(self, conf):
        buf = self.stream_buffers.get(self.s, b"") + self.data
        frames, rest, error = take_frames(buf)
        for frame in frames:
            self._handle_record(conf, frame)
            if self.s not in self.channel and self.s not in self.stream_buffers:
                return
        if error:
            print("\t - Grott invalid record: %s length=%s" % (error, len(buf)))
            self.stream_buffers[self.s] = b""
            self.on_close(conf)
            return
        if self.s in self.stream_buffers:
            self.stream_buffers[self.s] = rest

    def _handle_record(self, conf, data):
        print("")
        print("\t - " + "Growatt packet received:")
        peer = self.channel.get(self.s)
        print("\t\t ", peer if peer is not None else "noforward")

        decision = classify_proxy_record(conf, data)
        if decision != "forward":
            return

        # Default: send the original bytes to the Growatt server.
        # noforward is opt-in and does not change that default.
        if not getattr(conf, "noforward", False):
            self.channel[self.s].send(data)
        elif conf.verbose:
            print("\t - Grott noforward: record kept local and not sent upstream")

        if len(data) > conf.minrecl:
            # process received data
            procdata(conf, data)
        else:
            if conf.verbose:
                print("\t - " + "Data less then minimum record length, data not processed") 
                