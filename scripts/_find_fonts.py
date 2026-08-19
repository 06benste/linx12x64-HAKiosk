#!/usr/bin/env python3
import paramiko
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201",username="kioskuser",password="kiosk",timeout=20,allow_agent=False,look_for_keys=False)
_,o,_=c.exec_command("find /usr/share/fonts -name '*.ttf' 2>/dev/null | head -n 20")
print(o.read().decode())
c.close()
