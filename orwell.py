#!/usr/bin/python
from sys import stdin, argv
from threading import Thread 
from os import  getpid, unlink, kill, environ
from pathlib import Path
import threading
from rich.console import Console
import socket
import uuid as _uuid
from hashlib import sha1
import signal
import psutil
from time import sleep

class DbgBase:
    SUCCESS = 1
    DEBUG = 2
    INFO = 3
    ERROR = 4

    NEW_CMD = "::new_cmd::"
    END_CMD = "::end_cmd::"

    LOGGED_DIR_PATH = f"/home/{environ['USER']}/.logged"

    def __init__(self):
        self.socket_path = "/tmp/logger.sock"
        self.console = Console()
        self.uuid = None

    def here(self, uuid=None):
        self.dbg("here", self.DEBUG)

    def dbg_success(self, msg):
        self.dbg(msg, self.SUCCESS)
    
    def dbg_info(self, msg):
        self.dbg(msg, self.INFO)
    
    def dbg_err(self, msg):
        self.dbg(msg, self.ERROR)
    
    def dbg(self, msg, status):
        prefix = f"[[blue]{self.uuid}[/]] " if self.uuid != None else ""

        if status == self.SUCCESS:
            content = f"[[green]+[/]] {msg}"
        elif status == self.DEBUG:
            content = f"[[purple]+[/]] {msg}"
        elif status == self.INFO:
            content = f"[[yellow]+[/]] {msg}"
        elif status == self.ERROR:
            content = f"[[red]+[/]] {msg}"

        self.console.print(prefix + content)

class SocketWrapper:

    def __init__(self, connexion):
        self.connexion = connexion
        self.global_buffer = b""
    
    def recvuntil(self, delimiter):
        delimiter = delimiter.encode("utf-8")
        buffer = b""
        
        if delimiter in self.global_buffer:
            data = self.global_buffer[:self.global_buffer.index(delimiter) + 1]
            self.global_buffer = self.global_buffer[self.global_buffer.index(delimiter) + 1:]
            return data

        while (line := self.connexion.recv(1024)):
            if self.global_buffer != b"":
                line = self.global_buffer + line
                self.global_buffer = b""
            
            if delimiter in line:
                buffer += line[:line.index(delimiter) + 1]
                self.global_buffer = line[line.index(delimiter) + 1:]
                break
            
            buffer += line
        return buffer
    
    def recvline(self):
        return self.recvuntil("\n")
    
    def recv(self, nb):
        data = self.connexion.recv(nb)

        if self.global_buffer != b"":
            data = data + self.global_buffer
            self.global_buffer = b""
            return data

        return data
        

class LoggerClient(DbgBase):

    def __init__(self, argv):
        super().__init__()
        signal.signal(signal.SIGINT, self.bye)
        signal.signal(signal.SIGTERM, self.bye)
        signal.signal(signal.SIGALRM, self.bye)

        self.session = None
        self.pane_pid = None
        self.set = False
        self.setup(argv)

        self.dbg_success("client started")
        while True:
            if self.connect():
                self.read_and_send()
                self.connexion.close()
                self.dbg_success("client died\n")
            sleep(1)
    
    def bye(self, *args):
        self.connexion.close()
        unlink(self.instance_path)
        self.dbg_success("exited")
        exit(0)
    
    def check_pane(self):
        called = False
        while not called:
            sleep(5)
            if not psutil.pid_exists(self.pane_pid):
                self.dbg_info("pane exited")
                kill(getpid(), signal.SIGINT)
                called = True

    def setup(self, argv):
        self.session = argv[0]
        self.pane_pid = int(argv[3])
        self.instance_path = f"/tmp/{argv[0]}-{argv[1]}-{argv[2]}"
        with open(self.instance_path, "w") as f:
            f.write(str(getpid()))
        
        threading.Thread(target=self.check_pane).start()

        self.dbg_success(f"client setup at {self.instance_path}")
        
    def connect(self):
        self.uuid = str(_uuid.uuid4())[:8]
        self.dbg_info(f"connecting to {self.socket_path}")
        self.connexion = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.connexion.connect((self.socket_path))
        except FileNotFoundError:
            self.dbg_err("server seems not running")
            return False

        self.dbg_success("client connected")
        new_cmd = f"{self.NEW_CMD} {self.uuid} {self.session}\n".encode("utf-8")
        try:
            self.connexion.send(new_cmd)
        except BrokenPipeError:
            self.dbg_err("broken pipe")
            return False
        
        return True

    def read_and_send(self):
        self.dbg_info("tx begin")
        i = 0
        while "::end_cmd::" not in (line := stdin.readline()):
            if i == 2:
                if "\\" in line:
                    line = line.split("\\")[1]
            try:
                self.connexion.send(line.encode("utf-8"))
            except BrokenPipeError:
                self.dbg_err("broken pipe")
                break

            i += 1
        self.dbg_info("tx end")


class Worker(DbgBase, Thread):

    def __init__(self, connexion):
        super().__init__()
        Thread.__init__(self)
        self.connexion = connexion

    def ensure_env(self, dir_path):
        session_path = Path(dir_path)
        if not session_path.exists():
            session_path.mkdir()

    def log_cmd_index(self, cmd):
        index_path = f"{self.dir_path}/index"
        with open(index_path, "a") as f:
            f.write(cmd)
            f.write("\n")

    def run(self):
        if (line := self.connexion.recvline().decode("utf-8")).startswith(self.NEW_CMD):
            buffer = b""
            self.uuid = line.split(" ")[1]
            self.session = line.split(" ")[2][:-1]

            self.dbg_success("new connection")

            _ = self.connexion.recvline()
            cmd = self.connexion.recvline()
            self.dbg_info(cmd.decode("utf-8")[:-1])
            if cmd != b"":
                cmd = cmd.split(b" : ", 1)[1][:-1]
            
            outfile = sha1(cmd).hexdigest()

            self.dir_path = f"{self.LOGGED_DIR_PATH}/{self.session}"
            self.ensure_env(self.dir_path)
            outfile = f"{self.dir_path}/{outfile}.log"
            self.dbg_success(f"outfile will be {outfile}")

            while (line := self.connexion.recvline()) != b"":
                buffer += line

            out = open(outfile,"wb")
            out.write(buffer)
            out.close()
            if cmd != b"":
                self.log_cmd_index(cmd.decode("utf-8"))
            self.dbg_success("done\n")

class Logger(DbgBase):

    def __init__(self):
        super().__init__()
        # signal.signal(signal.SIGINT, self.__del__)
        # signal.signal(signal.SIGTERM, self.__del__)
        self.ensure_env()
        self.create_socket()
        self.listen()

    def create_socket(self):
        if Path(self.socket_path).exists():
            unlink(self.socket_path)
        self.dbg_success(f"using {self.socket_path}")
    
    def ensure_env(self):
        logged_path = Path(self.LOGGED_DIR_PATH)
        if not logged_path.exists():
            logged_path.mkdir()

    def new_connection(self, connexion):
        Worker(connexion).start()

    def listen(self):
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.socket_path)

        while True:
            self.server.listen(100)
            connexion, info = self.server.accept()
            self.new_connection(SocketWrapper(connexion))
        
    def __del__(self, *args):
        if Path(self.socket_path).exists():
            self.server.close()
            unlink(self.socket_path)
            exit(0)


if __name__ == "__main__":

    if len(argv) <= 1:
        print("missing client or server")
        exit(0)

    if argv[1] == "client":
        LoggerClient(argv[2:])
    elif argv[1] == "server":
        Logger()
    else:
        print("missing client or server")
        exit(0)